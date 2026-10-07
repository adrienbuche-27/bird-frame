<?php
// AvianVisitors - field recordings: audio recorded away from the station
// (a phone on a walk), uploaded here and analysed with BirdNET for the place
// and day it was recorded. Kept in <RECS_DIR>/Field (field.db + audio/),
// never in birds.db, so the collage, statistics and frame stay the
// station's own. The analysis runs in scripts/field_analysis.py.
//
// Every action requires the station admin: recordings carry where the
// owner has been.
//
//   GET  ?action=list             -> {recordings: [...]} newest first, each
//                                    with its species summary and detections
//   GET  ?action=audio&id=N       -> the uploaded file (supports Range)
//   POST ?action=begin   {name, size, lat, lon, recorded_at?, place?}
//                                 -> {id, chunk_bytes}
//   POST ?action=chunk   {id, offset, data}   data = base64, <= chunk_bytes
//   POST ?action=finish  {id}     -> queues the analysis
//   POST ?action=update  {id, lat?, lon?, recorded_at?, place?}
//                                 -> re-analyses when place or time changed
//   POST ?action=reanalyze {id}
//   POST ?action=delete  {id}
//
// Files travel in base64 chunks inside JSON so uploads keep the shared JSON
// action guard and stay under PHP's default post_max_size (8 MB).

declare(strict_types=1);

const FIELD_MAX_BYTES = 200 * 1024 * 1024;
const FIELD_CHUNK_BYTES = 2 * 1024 * 1024;
const FIELD_EXTENSIONS = ['wav', 'mp3', 'm4a', 'aac', 'ogg', 'oga', 'opus', 'flac', 'webm', '3gp', 'amr'];
const FIELD_STALE_UPLOAD_S = 24 * 3600;
const FIELD_PLACE_MAX = 120;

final class FieldError extends RuntimeException {
    public int $status;
    public function __construct(string $message, int $status = 400) {
        parent::__construct($message);
        $this->status = $status;
    }
}

function field_conf_value(string $conf, string $key): string {
    if (!is_readable($conf)) return '';
    foreach (file($conf, FILE_IGNORE_NEW_LINES) ?: [] as $line) {
        if (preg_match('/^\s*' . $key . '\s*=\s*(.*)$/', $line, $m)) {
            $v = trim($m[1]);
            if (strlen($v) >= 2 && ($v[0] === '"' || $v[0] === "'") && substr($v, -1) === $v[0]) {
                $v = substr($v, 1, -1);
            }
            return $v;
        }
    }
    return '';
}

/** <RECS_DIR>/Field, with $HOME as the station user's home (the checkout's parent). */
function field_dir(): string {
    $override = getenv('AV_FIELD_DIR');
    if (PHP_SAPI === 'cli' && is_string($override) && $override !== '') return $override;
    $home = dirname(__DIR__, 3);
    $recs = field_conf_value('/etc/birdnet/birdnet.conf', 'RECS_DIR');
    if ($recs === '') $recs = '$HOME/BirdSongs';
    return rtrim(str_replace(['${HOME}', '$HOME'], $home, $recs), '/') . '/Field';
}

function field_open_db(string $dir): SQLite3 {
    if (!is_dir("$dir/audio") && !@mkdir("$dir/audio", 0775, true) && !is_dir("$dir/audio")) {
        throw new FieldError("field recordings folder $dir is missing or not writable; see docs/field-recordings.md", 503);
    }
    if (!is_writable($dir) || !is_writable("$dir/audio")) {
        throw new FieldError("field recordings folder $dir is not writable; see docs/field-recordings.md", 503);
    }
    $schema = @file_get_contents(dirname(__DIR__, 2) . '/scripts/field_schema.sql');
    if (!is_string($schema)) throw new FieldError('field schema missing', 500);
    $db = new SQLite3("$dir/field.db");
    $db->enableExceptions(true);
    $db->busyTimeout(5000);
    $db->exec($schema);
    $db->exec('PRAGMA foreign_keys = ON');
    // SQLite creates field.db as 0644 whatever the umask; the owner's shell
    // and this web server share it. Its -wal/-shm files copy this mode.
    $stat = @stat("$dir/field.db");
    if (is_array($stat) && function_exists('posix_geteuid') && $stat['uid'] === posix_geteuid()
        && ($stat['mode'] & 0060) !== 0060) {
        @chmod("$dir/field.db", ($stat['mode'] & 0777) | 0060);
    }
    return $db;
}

// --- validation ---------------------------------------------------------

function field_id($value): int {
    if (!is_int($value) || $value < 1) throw new FieldError('bad id');
    return $value;
}

function field_coord($value, float $limit, string $label): float {
    if (!is_int($value) && !is_float($value)) throw new FieldError("bad $label");
    $v = (float)$value;
    if (!is_finite($v) || $v < -$limit || $v > $limit) throw new FieldError("bad $label");
    return round($v, 6);
}

/** "YYYY-MM-DDTHH:MM[:SS]" -> "YYYY-MM-DDTHH:MM:SS", or null when absent. */
function field_time($value): ?string {
    if ($value === null) return null;
    if (!is_string($value) || !preg_match('/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/', $value, $m)) {
        throw new FieldError('recorded_at must look like 2026-10-06T07:30');
    }
    [$y, $mo, $d, $h, $mi, $s] = [(int)$m[1], (int)$m[2], (int)$m[3], (int)$m[4], (int)$m[5], (int)($m[6] ?? 0)];
    if (!checkdate($mo, $d, $y) || $h > 23 || $mi > 59 || $s > 59 || $y < 2000) {
        throw new FieldError('recorded_at is not a valid date');
    }
    return sprintf('%04d-%02d-%02dT%02d:%02d:%02d', $y, $mo, $d, $h, $mi, $s);
}

function field_place($value): string {
    if ($value === null) return '';
    if (!is_string($value)) throw new FieldError('bad place');
    $clean = trim((string)preg_replace('/[\x00-\x1F\x7F]+/u', ' ', $value));
    if (!mb_check_encoding($clean, 'UTF-8') || mb_strlen($clean) > FIELD_PLACE_MAX) {
        throw new FieldError('place must be at most ' . FIELD_PLACE_MAX . ' characters');
    }
    return $clean;
}

function field_extension($name): string {
    if (!is_string($name) || $name === '' || strlen($name) > 255) throw new FieldError('bad file name');
    $ext = strtolower(pathinfo($name, PATHINFO_EXTENSION));
    if (!in_array($ext, FIELD_EXTENSIONS, true)) {
        throw new FieldError('unsupported audio type; use ' . implode(', ', FIELD_EXTENSIONS), 415);
    }
    return $ext;
}

/** @param array<string, mixed> $fields */
function field_only(array $fields, array $allowed): void {
    if (array_diff(array_keys($fields), $allowed)) throw new FieldError('unexpected field');
}

function field_now(): string {
    return date('Y-m-d\TH:i:s');
}

// --- storage ------------------------------------------------------------

function field_row(SQLite3 $db, int $id): array {
    $st = $db->prepare('SELECT * FROM recordings WHERE id = :id');
    $st->bindValue(':id', $id, SQLITE3_INTEGER);
    $row = $st->execute()->fetchArray(SQLITE3_ASSOC);
    if (!$row) throw new FieldError('no such recording', 404);
    return $row;
}

function field_part_path(string $dir, array $row): string {
    return "$dir/audio/{$row['stored_name']}.part";
}

/** Drop uploads abandoned for a day so half-sent files do not pile up. */
function field_purge_stale(SQLite3 $db, string $dir): void {
    $cutoff = date('Y-m-d\TH:i:s', time() - FIELD_STALE_UPLOAD_S);
    $st = $db->prepare("SELECT * FROM recordings WHERE status = 'uploading' AND created_at < :c");
    $st->bindValue(':c', $cutoff, SQLITE3_TEXT);
    $res = $st->execute();
    $ids = [];
    while ($row = $res->fetchArray(SQLITE3_ASSOC)) {
        @unlink(field_part_path($dir, $row));
        $ids[] = (int)$row['id'];
    }
    foreach ($ids as $id) $db->exec('DELETE FROM recordings WHERE id = ' . $id);
}

/** @param array<string, mixed> $f */
function field_begin(SQLite3 $db, string $dir, array $f): array {
    field_only($f, ['name', 'size', 'lat', 'lon', 'recorded_at', 'place']);
    $ext = field_extension($f['name'] ?? null);
    $size = $f['size'] ?? null;
    if (!is_int($size) || $size < 1) throw new FieldError('bad size');
    if ($size > FIELD_MAX_BYTES) throw new FieldError('file is larger than ' . (FIELD_MAX_BYTES >> 20) . ' MB', 413);
    $lat = field_coord($f['lat'] ?? null, 90, 'latitude');
    $lon = field_coord($f['lon'] ?? null, 180, 'longitude');
    $recordedAt = field_time($f['recorded_at'] ?? null);
    $place = field_place($f['place'] ?? null);

    field_purge_stale($db, $dir);
    $st = $db->prepare("INSERT INTO recordings (original_name, stored_name, size_bytes, recorded_at, lat, lon, place, "
        . "status, created_at) VALUES (:n, '', :s, :r, :lat, :lon, :p, 'uploading', :c)");
    $st->bindValue(':n', basename((string)$f['name']), SQLITE3_TEXT);
    $st->bindValue(':s', $size, SQLITE3_INTEGER);
    $st->bindValue(':r', $recordedAt, $recordedAt === null ? SQLITE3_NULL : SQLITE3_TEXT);
    $st->bindValue(':lat', $lat, SQLITE3_FLOAT);
    $st->bindValue(':lon', $lon, SQLITE3_FLOAT);
    $st->bindValue(':p', $place, SQLITE3_TEXT);
    $st->bindValue(':c', field_now(), SQLITE3_TEXT);
    $st->execute();
    $id = (int)$db->lastInsertRowID();
    $stored = "$id.$ext";
    $db->exec("UPDATE recordings SET stored_name = '$stored' WHERE id = $id");
    if (@file_put_contents("$dir/audio/$stored.part", '') === false) {
        $db->exec("DELETE FROM recordings WHERE id = $id");
        throw new FieldError('could not create the upload file', 503);
    }
    return ['ok' => true, 'id' => $id, 'chunk_bytes' => FIELD_CHUNK_BYTES];
}

/** @param array<string, mixed> $f */
function field_chunk(SQLite3 $db, string $dir, array $f): array {
    field_only($f, ['id', 'offset', 'data']);
    $row = field_row($db, field_id($f['id'] ?? null));
    if ($row['status'] !== 'uploading') throw new FieldError('upload already finished', 409);
    $offset = $f['offset'] ?? null;
    if (!is_int($offset) || $offset < 0) throw new FieldError('bad offset');
    $data = $f['data'] ?? null;
    if (!is_string($data) || strlen($data) > intdiv(FIELD_CHUNK_BYTES + 2, 3) * 4) throw new FieldError('chunk too large', 413);
    $bytes = base64_decode($data, true);
    if ($bytes === false || $bytes === '') throw new FieldError('chunk is not base64');

    $part = field_part_path($dir, $row);
    $handle = @fopen($part, 'r+b');
    if ($handle === false) throw new FieldError('upload file is missing', 409);
    try {
        flock($handle, LOCK_EX);
        $have = fstat($handle)['size'];
        if ($offset !== $have) throw new FieldError("expected offset $have", 409);
        if ($have + strlen($bytes) > (int)$row['size_bytes']) throw new FieldError('more data than announced', 413);
        fseek($handle, $have);
        if (fwrite($handle, $bytes) !== strlen($bytes)) throw new FieldError('could not store the chunk', 507);
        fflush($handle);
        return ['ok' => true, 'received' => $have + strlen($bytes)];
    } finally {
        flock($handle, LOCK_UN);
        fclose($handle);
    }
}

/** @param array<string, mixed> $f */
function field_finish(SQLite3 $db, string $dir, array $f): array {
    field_only($f, ['id']);
    $row = field_row($db, field_id($f['id'] ?? null));
    if ($row['status'] !== 'uploading') throw new FieldError('upload already finished', 409);
    $part = field_part_path($dir, $row);
    clearstatcache(true, $part);
    $have = @filesize($part);
    if ($have !== (int)$row['size_bytes']) throw new FieldError('upload incomplete', 409);
    if (!@rename($part, "$dir/audio/{$row['stored_name']}")) throw new FieldError('could not store the file', 503);
    $db->exec("UPDATE recordings SET status = 'queued' WHERE id = " . (int)$row['id']);
    return ['ok' => true, 'id' => (int)$row['id'], 'status' => 'queued'];
}

/** @param array<string, mixed> $f */
function field_update(SQLite3 $db, array $f): array {
    field_only($f, ['id', 'lat', 'lon', 'recorded_at', 'place']);
    $row = field_row($db, field_id($f['id'] ?? null));
    if ($row['status'] === 'analyzing') throw new FieldError('recording is being analysed; try again shortly', 409);
    $set = [];
    $rerun = false;
    if (array_key_exists('lat', $f)) {
        $set['lat'] = field_coord($f['lat'], 90, 'latitude');
        $rerun = $rerun || $set['lat'] !== (float)$row['lat'];
    }
    if (array_key_exists('lon', $f)) {
        $set['lon'] = field_coord($f['lon'], 180, 'longitude');
        $rerun = $rerun || $set['lon'] !== (float)$row['lon'];
    }
    if (array_key_exists('recorded_at', $f)) {
        $set['recorded_at'] = field_time($f['recorded_at']);
        $rerun = $rerun || $set['recorded_at'] !== $row['recorded_at'];
    }
    if (array_key_exists('place', $f)) $set['place'] = field_place($f['place']);
    if (!$set) throw new FieldError('nothing to update');
    // Place and time decide which species the range model admits.
    if ($rerun && in_array($row['status'], ['done', 'error'], true)) $set['status'] = 'queued';
    $sql = 'UPDATE recordings SET ' . implode(', ', array_map(fn($k) => "$k = :$k", array_keys($set))) . ' WHERE id = :id';
    $st = $db->prepare($sql);
    foreach ($set as $k => $v) {
        $st->bindValue(":$k", $v, $v === null ? SQLITE3_NULL : (is_float($v) ? SQLITE3_FLOAT : SQLITE3_TEXT));
    }
    $st->bindValue(':id', (int)$row['id'], SQLITE3_INTEGER);
    $st->execute();
    return ['ok' => true, 'id' => (int)$row['id'], 'status' => $set['status'] ?? $row['status']];
}

/** @param array<string, mixed> $f */
function field_reanalyze(SQLite3 $db, array $f): array {
    field_only($f, ['id']);
    $row = field_row($db, field_id($f['id'] ?? null));
    if (!in_array($row['status'], ['done', 'error'], true)) throw new FieldError('recording is not analysed yet', 409);
    $db->exec("UPDATE recordings SET status = 'queued' WHERE id = " . (int)$row['id']);
    return ['ok' => true, 'id' => (int)$row['id'], 'status' => 'queued'];
}

/** @param array<string, mixed> $f */
function field_delete(SQLite3 $db, string $dir, array $f): array {
    field_only($f, ['id']);
    $row = field_row($db, field_id($f['id'] ?? null));
    if ($row['status'] === 'analyzing') throw new FieldError('recording is being analysed; try again shortly', 409);
    @unlink("$dir/audio/{$row['stored_name']}");
    @unlink(field_part_path($dir, $row));
    $db->exec('DELETE FROM recordings WHERE id = ' . (int)$row['id']);
    return ['ok' => true, 'id' => (int)$row['id']];
}

function field_list(SQLite3 $db): array {
    $recordings = [];
    $res = $db->query("SELECT * FROM recordings WHERE status != 'uploading' ORDER BY COALESCE(recorded_at, created_at) DESC, id DESC");
    while ($row = $res->fetchArray(SQLITE3_ASSOC)) {
        $recordings[(int)$row['id']] = [
            'id' => (int)$row['id'],
            'name' => $row['original_name'],
            'recorded_at' => $row['recorded_at'],
            'lat' => (float)$row['lat'],
            'lon' => (float)$row['lon'],
            'place' => $row['place'],
            'status' => $row['status'],
            'error' => $row['error'],
            'duration_s' => $row['duration_s'] === null ? null : (float)$row['duration_s'],
            'size_bytes' => (int)$row['size_bytes'],
            'created_at' => $row['created_at'],
            'analyzed_at' => $row['analyzed_at'],
            'species' => [],
            'detections' => [],
        ];
    }
    $res = $db->query('SELECT * FROM detections ORDER BY recording_id, start_s, confidence DESC');
    while ($d = $res->fetchArray(SQLITE3_ASSOC)) {
        $id = (int)$d['recording_id'];
        if (!isset($recordings[$id])) continue;
        $recordings[$id]['detections'][] = [
            'sci' => $d['sci_name'], 'com' => $d['com_name'],
            'confidence' => (float)$d['confidence'], 'start' => (float)$d['start_s'], 'end' => (float)$d['end_s'],
        ];
        $s = &$recordings[$id]['species'][$d['sci_name']];
        $s = [
            'sci' => $d['sci_name'], 'com' => $d['com_name'],
            'n' => ($s['n'] ?? 0) + 1, 'best' => max($s['best'] ?? 0.0, (float)$d['confidence']),
        ];
        unset($s);
    }
    foreach ($recordings as &$r) {
        $species = array_values($r['species']);
        usort($species, fn($a, $b) => $b['best'] <=> $a['best']);
        $r['species'] = $species;
    }
    unset($r);
    return ['ok' => true, 'recordings' => array_values($recordings)];
}

// --- worker -------------------------------------------------------------

function field_find_executable(string $name): ?string {
    // PHP-FPM clears PATH unless the pool explicitly supplies it.
    $path = (string)getenv('PATH');
    $directories = $path !== ''
        ? explode(PATH_SEPARATOR, $path)
        : ['/usr/local/sbin', '/usr/local/bin', '/usr/sbin', '/usr/bin', '/sbin', '/bin'];
    foreach ($directories as $directory) {
        if ($directory === '' || $directory[0] !== DIRECTORY_SEPARATOR) continue;
        $candidate = rtrim($directory, DIRECTORY_SEPARATOR) . DIRECTORY_SEPARATOR . $name;
        if (is_file($candidate) && is_executable($candidate)) return $candidate;
    }
    return null;
}

/** Start scripts/field_analysis.py in the background. It locks, so extra starts are harmless. */
function field_spawn_worker(string $dir): bool {
    $root = dirname(__DIR__, 2);
    $python = "$root/birdnet/bin/python3";
    if (!is_executable($python)) $python = field_find_executable('python3') ?? '';
    $nohup = field_find_executable('nohup') ?? '';
    $script = "$root/scripts/field_analysis.py";
    if ($python === '' || $nohup === '' || !is_readable($script) || !function_exists('proc_open')) return false;
    $log = "$dir/worker.log";
    if (!is_dir("$dir/.cache")) @mkdir("$dir/.cache", 0775);
    // PHP-FPM runs with an empty PATH and the web server's HOME: give the
    // worker what ffmpeg lookup and numba's cache (via librosa) need.
    $environment = [
        'PATH' => '/usr/local/bin:/usr/bin:/bin',
        'HOME' => "$dir/.cache",
        'NUMBA_CACHE_DIR' => "$dir/.cache",
        'LANG' => 'C.UTF-8',
    ];
    $cmd = escapeshellarg($nohup) . ' ' . escapeshellarg($python) . ' ' . escapeshellarg($script)
         . ' --field-dir ' . escapeshellarg($dir) . ' run'
         . ' >> ' . escapeshellarg($log) . ' 2>&1 < /dev/null &';
    $process = @proc_open(['/bin/sh', '-c', $cmd],
        [0 => ['file', '/dev/null', 'r'], 1 => ['file', '/dev/null', 'a'], 2 => ['file', '/dev/null', 'a']],
        $pipes, "$root/scripts", $environment, ['bypass_shell' => true]);
    return is_resource($process) && proc_close($process) === 0;
}

// --- audio --------------------------------------------------------------

function field_serve_audio(string $dir, array $row): void {
    $path = "$dir/audio/{$row['stored_name']}";
    if ($row['status'] === 'uploading' || !is_file($path)) throw new FieldError('audio not available', 404);
    $types = ['wav' => 'audio/wav', 'mp3' => 'audio/mpeg', 'm4a' => 'audio/mp4', 'aac' => 'audio/aac',
        'ogg' => 'audio/ogg', 'oga' => 'audio/ogg', 'opus' => 'audio/ogg', 'flac' => 'audio/flac',
        'webm' => 'audio/webm', '3gp' => 'audio/3gpp', 'amr' => 'audio/amr'];
    $ext = strtolower(pathinfo($path, PATHINFO_EXTENSION));
    $size = filesize($path);
    $start = 0;
    $end = $size - 1;
    if (preg_match('/^bytes=(\d*)-(\d*)$/', (string)($_SERVER['HTTP_RANGE'] ?? ''), $m) && ($m[1] !== '' || $m[2] !== '')) {
        if ($m[1] === '') {
            $start = max(0, $size - (int)$m[2]);
        } else {
            $start = (int)$m[1];
            if ($m[2] !== '') $end = min($end, (int)$m[2]);
        }
        if ($start > $end || $start >= $size) {
            header("Content-Range: bytes */$size");
            http_response_code(416);
            exit;
        }
        http_response_code(206);
        header("Content-Range: bytes $start-$end/$size");
    }
    header('Content-Type: ' . ($types[$ext] ?? 'application/octet-stream'));
    header('Accept-Ranges: bytes');
    header('X-Content-Type-Options: nosniff');
    header('Content-Length: ' . ($end - $start + 1));
    header('Cache-Control: private, max-age=3600');
    $handle = fopen($path, 'rb');
    fseek($handle, $start);
    $left = $end - $start + 1;
    while ($left > 0 && !feof($handle)) {
        $buf = fread($handle, min(65536, $left));
        if ($buf === false) break;
        echo $buf;
        $left -= strlen($buf);
    }
    fclose($handle);
    exit;
}

/** Common name of a species found in a field recording, or null. Read-only. */
function field_species_common_name(string $sci): ?string {
    $path = field_dir() . '/field.db';
    if (!is_file($path)) return null;
    try {
        $db = new SQLite3($path, SQLITE3_OPEN_READONLY);
        $db->busyTimeout(2000);
        $st = $db->prepare('SELECT com_name FROM detections WHERE sci_name = :s ORDER BY id DESC LIMIT 1');
        $st->bindValue(':s', $sci, SQLITE3_TEXT);
        $row = $st->execute()->fetchArray(SQLITE3_ASSOC);
        $db->close();
    } catch (Throwable $e) {
        return null;
    }
    return $row ? (string)$row['com_name'] : null;
}

if (defined('AVIAN_FIELD_LIBRARY_ONLY')) return;

// --- dispatch -----------------------------------------------------------

require_once __DIR__ . '/admin-auth.php';
avian_require_admin();

function field_fail(int $status, string $error): void {
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store');
    echo json_encode(['ok' => false, 'error' => $error]);
    exit;
}

$action = $_GET['action'] ?? 'list';
umask(0002);  // the owner's command-line tool shares these files
try {
    $dir = field_dir();
    $db = field_open_db($dir);

    if ($action === 'audio') {
        $id = filter_var($_GET['id'] ?? null, FILTER_VALIDATE_INT, ['options' => ['min_range' => 1]]);
        if ($id === false) throw new FieldError('bad id');
        field_serve_audio($dir, field_row($db, $id));
    }

    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store');
    if ($action === 'list') {
        echo json_encode(field_list($db), JSON_INVALID_UTF8_SUBSTITUTE);
        exit;
    }

    $handlers = ['begin', 'chunk', 'finish', 'update', 'reanalyze', 'delete'];
    if (!in_array($action, $handlers, true)) throw new FieldError('unknown action', 404);
    avian_require_json_action();
    try {
        $body = json_decode((string)file_get_contents('php://input'), true, 8, JSON_THROW_ON_ERROR);
    } catch (JsonException $e) {
        throw new FieldError('invalid JSON body');
    }
    if (!is_array($body) || array_is_list($body) && $body !== []) throw new FieldError('JSON object required');

    $result = match ($action) {
        'begin' => field_begin($db, $dir, $body),
        'chunk' => field_chunk($db, $dir, $body),
        'finish' => field_finish($db, $dir, $body),
        'update' => field_update($db, $body),
        'reanalyze' => field_reanalyze($db, $body),
        'delete' => field_delete($db, $dir, $body),
    };
    if (($result['status'] ?? null) === 'queued' && !field_spawn_worker($dir)) {
        $result['warning'] = 'queued, but the analysis worker could not be started';
    }
    echo json_encode($result, JSON_INVALID_UTF8_SUBSTITUTE);
} catch (FieldError $e) {
    field_fail($e->status, $e->getMessage());
} catch (Throwable $e) {
    error_log('field.php: ' . $e->getMessage());
    field_fail(500, 'field recordings unavailable');
}
