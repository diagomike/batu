<?php
/* Apply for a service (form on /services/<id>/apply). Mirrors POST /services/{sid}/apply in app/main.py. */
require __DIR__ . '/lib.php';
require_post();
rate_limit('apply', 10, 3600);

$services = cat('services');
$sid = (string)($_GET['service'] ?? '');
if (!isset($services[$sid])) fail('That service was not found.', 404);
$name = field('name', 120);
if ($name === '') fail('Please give your name.');

$s = $services[$sid];
$amount = !empty($s['fee']) ? (float)$s['fee'] : null;
$ref = create_request('application', 'A', $sid, $s['title'],
    ['name' => $name, 'phone' => field('phone', 40), 'kebele' => field('kebele', 80),
     'details' => field('details', 4000), 'visit_date' => field('visit_date', 10)], $amount);
go(lang_prefix() . 'track/?ref=' . rawurlencode($ref) . '&new=1');
