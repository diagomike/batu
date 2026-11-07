<?php
/* GET /api/request/<ref>: the public status of a request for the tracking page (no personal details). */
require __DIR__ . '/lib.php';
rate_limit('track', 60, 600);
$ref = (string)($_GET['ref'] ?? '');
if (!preg_match('/^[A-Za-z0-9-]{4,40}$/', $ref)) json_out(['error' => 'not found'], 404);
$r = get_request($ref);
if (!$r) json_out(['error' => 'not found'], 404);
json_out(public_request($r) + ['payments' => cfg('payments', 'off')]);
