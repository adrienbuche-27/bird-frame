<?php
declare(strict_types=1);

// Field recordings API: validation, chunked upload and record keeping.
// Run by tests/test_field_api.py; exits non-zero on any failure.

define('AVIAN_FIELD_LIBRARY_ONLY', true);
require_once dirname(__DIR__) . '/avian/api/field.php';

$checks = 0;
$failures = 0;

function check_field(bool $condition, string $label): void {
    global $checks, $failures;
    $checks++;
    if ($condition) return;
    $failures++;
    fwrite(STDERR, "FAIL: $label\n");
}

/** Expect a FieldError with the given HTTP status. */
function rejects(callable $fn, int $status, string $label): void {
    try {
        $fn();
        check_field(false, "$label (no error)");
    } catch (FieldError $e) {
        check_field($e->status === $status, "$label (got {$e->status}: {$e->getMessage()})");
    }
}

$dir = sys_get_temp_dir() . '/field-api-' . bin2hex(random_bytes(4));
mkdir($dir);
$db = field_open_db($dir);
check_field(is_dir("$dir/audio"), 'audio folder is created');
clearstatcache();
check_field((fileperms("$dir/field.db") & 0060) === 0060, 'field.db is group-writable for the shell and the web server');

// --- validation --------------------------------------------------------
check_field(field_time('2026-10-06T07:30') === '2026-10-06T07:30:00', 'minutes-only time gets seconds');
check_field(field_time(null) === null, 'missing time stays unknown');
rejects(fn() => field_time('2026-02-30T07:30'), 400, 'impossible date');
rejects(fn() => field_time('06/10/2026'), 400, 'other date format');
check_field(field_place("  Bois\x07 de\nVincennes ") === 'Bois  de Vincennes', 'control characters stripped');
rejects(fn() => field_place(str_repeat('é', FIELD_PLACE_MAX + 1)), 400, 'place too long');
check_field(field_extension('Voice 001.M4A') === 'm4a', 'extension is case-insensitive');
rejects(fn() => field_extension('notes.txt'), 415, 'non-audio file');
rejects(fn() => field_extension('../../x.php'), 415, 'path tricks are not audio');
rejects(fn() => field_coord(91, 90, 'latitude'), 400, 'latitude out of range');
rejects(fn() => field_coord('48.8', 90, 'latitude'), 400, 'latitude as string');
check_field(field_coord(48.85661234567, 90, 'latitude') === 48.856612, 'coordinates rounded to 6 decimals');

$good = ['name' => 'walk.m4a', 'size' => 10, 'lat' => 48.85, 'lon' => 2.35];
rejects(fn() => field_begin($db, $dir, $good + ['extra' => 1]), 400, 'unknown field');
rejects(fn() => field_begin($db, $dir, ['size' => FIELD_MAX_BYTES + 1] + $good), 413, 'too large');
rejects(fn() => field_begin($db, $dir, ['size' => 0] + $good), 400, 'empty file');

// --- chunked upload ----------------------------------------------------
$payload = random_bytes(10);
$begin = field_begin($db, $dir, ['recorded_at' => '2026-05-01T06:15', 'place' => 'Bois'] + $good);
$id = $begin['id'];
check_field($begin['chunk_bytes'] === FIELD_CHUNK_BYTES, 'chunk size announced');
check_field(field_list($db)['recordings'] === [], 'uploads in progress are not listed');
rejects(fn() => field_finish($db, $dir, ['id' => $id]), 409, 'finish before all data');
rejects(fn() => field_chunk($db, $dir, ['id' => $id, 'offset' => 4, 'data' => base64_encode('ab')]), 409, 'gap in offsets');
rejects(fn() => field_chunk($db, $dir, ['id' => $id, 'offset' => 0, 'data' => '!!!']), 400, 'invalid base64');
$r = field_chunk($db, $dir, ['id' => $id, 'offset' => 0, 'data' => base64_encode(substr($payload, 0, 6))]);
check_field($r['received'] === 6, 'first chunk stored');
rejects(fn() => field_chunk($db, $dir, ['id' => $id, 'offset' => 6, 'data' => base64_encode('12345')]), 413, 'more than announced');
field_chunk($db, $dir, ['id' => $id, 'offset' => 6, 'data' => base64_encode(substr($payload, 6))]);
$done = field_finish($db, $dir, ['id' => $id]);
check_field($done['status'] === 'queued', 'finished upload is queued');
check_field(file_get_contents("$dir/audio/$id.m4a") === $payload, 'file stored byte for byte');
check_field(!file_exists("$dir/audio/$id.m4a.part"), 'part file renamed');
rejects(fn() => field_chunk($db, $dir, ['id' => $id, 'offset' => 10, 'data' => base64_encode('x')]), 409, 'no chunk after finish');

$list = field_list($db)['recordings'];
check_field(count($list) === 1 && $list[0]['place'] === 'Bois' && $list[0]['recorded_at'] === '2026-05-01T06:15:00',
    'listed with place and time');
check_field($list[0]['status'] === 'queued' && $list[0]['species'] === [], 'queued without detections');

// --- results, edits, re-analysis ---------------------------------------
$db->exec("UPDATE recordings SET status = 'done' WHERE id = $id");
$db->exec("INSERT INTO detections (recording_id, sci_name, com_name, confidence, start_s, end_s) VALUES
    ($id, 'Pica pica', 'Eurasian Magpie', 0.81, 3, 6),
    ($id, 'Pica pica', 'Eurasian Magpie', 0.93, 9, 12),
    ($id, 'Erithacus rubecula', 'European Robin', 0.75, 12, 15)");
$rec = field_list($db)['recordings'][0];
check_field(array_column($rec['species'], 'sci') === ['Pica pica', 'Erithacus rubecula'], 'species sorted by best confidence');
check_field($rec['species'][0]['n'] === 2 && $rec['species'][0]['best'] === 0.93, 'species summary counts and best');
check_field(count($rec['detections']) === 3, 'every detection listed');

$u = field_update($db, ['id' => $id, 'place' => 'Bois de Boulogne']);
check_field($u['status'] === 'done', 'renaming the place does not re-analyse');
$u = field_update($db, ['id' => $id, 'recorded_at' => '2026-05-02T06:15']);
check_field($u['status'] === 'queued', 'changing the time re-analyses');
$db->exec("UPDATE recordings SET status = 'analyzing' WHERE id = $id");
rejects(fn() => field_update($db, ['id' => $id, 'lat' => 10]), 409, 'no edit while analysing');
rejects(fn() => field_delete($db, $dir, ['id' => $id]), 409, 'no delete while analysing');
rejects(fn() => field_reanalyze($db, ['id' => $id]), 409, 'no re-analysis while analysing');
$db->exec("UPDATE recordings SET status = 'error' WHERE id = $id");
check_field(field_reanalyze($db, ['id' => $id])['status'] === 'queued', 'failed recording can be re-analysed');
rejects(fn() => field_update($db, ['id' => $id]), 400, 'empty update');
rejects(fn() => field_update($db, ['id' => 9999, 'place' => 'x']), 404, 'unknown recording');

field_delete($db, $dir, ['id' => $id]);
check_field(field_list($db)['recordings'] === [], 'deleted recording gone');
check_field(!file_exists("$dir/audio/$id.m4a"), 'deleted audio removed');
check_field((int)$db->querySingle('SELECT COUNT(*) FROM detections') === 0, 'detections removed with it');

// --- abandoned uploads -------------------------------------------------
$stale = field_begin($db, $dir, $good)['id'];
$db->exec("UPDATE recordings SET created_at = '2000-01-01T00:00:00' WHERE id = $stale");
field_begin($db, $dir, $good);
check_field($db->querySingle("SELECT COUNT(*) FROM recordings WHERE id = $stale") === 0, 'stale upload purged');
check_field(!file_exists("$dir/audio/$stale.m4a.part"), 'stale part file removed');

// --- folder resolution -------------------------------------------------
putenv('AV_FIELD_DIR');
check_field(str_ends_with(field_dir(), '/BirdSongs/Field'), 'defaults to <home>/BirdSongs/Field');

$db->close();
array_map('unlink', glob("$dir/audio/*") ?: []);
rmdir("$dir/audio");
array_map('unlink', glob("$dir/*") ?: []);
rmdir($dir);

echo "$checks checks, $failures failures\n";
exit($failures === 0 ? 0 : 1);
