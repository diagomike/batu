<?php
/* Report a problem or make a complaint (form on /report). Mirrors POST /report in app/main.py. */
require __DIR__ . '/lib.php';
require_post();
rate_limit('report', 8, 3600);

$details = field('details', 4000);
if ($details === '') fail('Please describe the problem.');
$kind = field('kind', 20) === 'complaint' ? 'complaint' : 'report';
$type = field('type', 120);
$data = ['type' => $type, 'where' => field('where', 300), 'kebele' => field('kebele', 80),
         'details' => $details, 'phone' => field('phone', 40)];

$f = $_FILES['photo'] ?? null;
if ($f && is_array($f) && ($f['error'] ?? UPLOAD_ERR_NO_FILE) === UPLOAD_ERR_OK && $f['size'] > 0) {
    $info = @getimagesize($f['tmp_name']);
    $ext = [IMAGETYPE_JPEG => '.jpg', IMAGETYPE_PNG => '.png', IMAGETYPE_WEBP => '.webp'][$info[2] ?? 0] ?? null;
    if ($ext && $f['size'] <= 6000000) {
        $dir = cfg('uploads_dir');
        if (!is_dir($dir)) mkdir($dir, 0750, true);
        $name = bin2hex(random_bytes(6)) . $ext;
        if (move_uploaded_file($f['tmp_name'], $dir . '/' . $name)) $data['photo'] = $name;
    }
}

$complaint = $kind === 'complaint';
$ref = create_request($kind, $complaint ? 'C' : 'R', null,
    $complaint ? 'Complaint about a service' : ($type !== '' ? $type : 'Problem report'), $data);
go(lang_prefix() . 'track/?ref=' . rawurlencode($ref) . '&new=1');
