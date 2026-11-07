<?php
/* Book a boat trip or a venue (form on /book). Mirrors POST /book in app/main.py. */
require __DIR__ . '/lib.php';
require_post();
rate_limit('book', 10, 3600);

$trips = cat('trips');
$trip = field('trip', 40);
if (!isset($trips[$trip])) fail('Please choose a trip.');
$date = field('date', 10);
if (!preg_match('/^\d{4}-\d{2}-\d{2}$/', $date)) fail('Please choose a date.');
$name = field('name', 120);
if ($name === '') fail('Please give the name for the booking.');
$people = max(1, min(60, (int)field('people', 3)));

$t = $trips[$trip];
$ref = create_request('booking', 'B', $trip === 'venue' ? 'venue-booking' : 'boat-tour', $t['title'],
    ['trip' => $trip, 'date' => $date, 'people' => $people, 'name' => $name, 'phone' => field('phone', 40)], $t['price']);
go(lang_prefix() . 'pay/?ref=' . rawurlencode($ref));
