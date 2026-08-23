<?php

function Minhnhatdev_icon(string $name, string $class = '', int $size = 18): string {
    $paths = [
        'shield-search' => '<circle cx="8.25" cy="8.25" r="5.25" stroke="currentColor" stroke-width="1.4"/><path d="M12.2 12.2L15.75 15.75" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/><path d="M6.6 8.1L7.9 9.4L10 7.2" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/>',
        'user' => '<circle cx="9" cy="5.25" r="3" stroke="currentColor" stroke-width="1.4"/><path d="M2.75 15.25C2.75 12.4 5.55 10.5 9 10.5C12.45 10.5 15.25 12.4 15.25 15.25" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>',
        'users' => '<circle cx="6.75" cy="5.5" r="2.5" stroke="currentColor" stroke-width="1.3"/><path d="M2.25 14.75C2.25 12.4 4.2 10.75 6.75 10.75C9.3 10.75 11.25 12.4 11.25 14.75" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/><circle cx="12" cy="6" r="2" stroke="currentColor" stroke-width="1.3"/><path d="M13.6 10.9C15.2 11.3 16.25 12.8 16.25 14.75" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/>',
        'plus' => '<path d="M9 3.5V14.5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/><path d="M3.5 9H14.5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>',
        'time' => '<circle cx="9" cy="9" r="6.5" stroke="currentColor" stroke-width="1.4"/><path d="M9 5.5V9L11.5 10.75" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/>',
        'settings' => '<circle cx="9" cy="9" r="2.25" stroke="currentColor" stroke-width="1.4"/><path d="M9 2.5V4.25M9 13.75V15.5M15.5 9H13.75M4.25 9H2.5M13.6 4.4L12.35 5.65M5.65 12.35L4.4 13.6M13.6 13.6L12.35 12.35M5.65 5.65L4.4 4.4" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>',
        'logout' => '<path d="M10.5 2.75H5C3.895 2.75 3 3.645 3 4.75V13.25C3 14.355 3.895 15.25 5 15.25H10.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/><path d="M13 5.75L16.25 9L13 12.25" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/><path d="M16.25 9H7.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>',
        'check' => '<path d="M3 9.5L7 13.5L15 4.5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>',
        'double-check' => '<path d="M1.75 9.5L5 12.75L11.75 5.25" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/><path d="M7.25 12.25L9 14L16.25 5.75" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>',
        'cross' => '<path d="M4.5 4.5L13.5 13.5M13.5 4.5L4.5 13.5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>',
        'copy' => '<rect x="6.25" y="6.25" width="9" height="9" rx="1.5" stroke="currentColor" stroke-width="1.4"/><path d="M11.75 3.75V3.5C11.75 2.81 11.19 2.25 10.5 2.25H4C3.31 2.25 2.75 2.81 2.75 3.5V10C2.75 10.69 3.31 11.25 4 11.25H4.25" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>',
        'info' => '<circle cx="9" cy="9" r="6.5" stroke="currentColor" stroke-width="1.4"/><path d="M9 8V12.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/><circle cx="9" cy="5.5" r="0.9" fill="currentColor"/>',
        'menu' => '<path d="M2.75 5H15.25M2.75 9H15.25M2.75 13H10.25" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>',
        'eye' => '<path d="M2.25 9C3.4 5.9 5.95 4 9 4C12.05 4 14.6 5.9 15.75 9C14.6 12.1 12.05 14 9 14C5.95 14 3.4 12.1 2.25 9Z" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/><circle cx="9" cy="9" r="2" stroke="currentColor" stroke-width="1.4"/>',
        'wallet' => '<path d="M2.75 6C2.75 4.76 3.76 3.75 5 3.75H13C14.24 3.75 15.25 4.76 15.25 6V12.5C15.25 13.74 14.24 14.75 13 14.75H5C3.76 14.75 2.75 13.74 2.75 12.5V6Z" stroke="currentColor" stroke-width="1.4"/><path d="M15.25 7.25H12.5C11.4 7.25 10.5 8.15 10.5 9.25C10.5 10.35 11.4 11.25 12.5 11.25H15.25" stroke="currentColor" stroke-width="1.4"/><circle cx="12.6" cy="9.25" r="0.8" fill="currentColor"/>',
        'crown' => '<path d="M2.75 13.25L2 5.75L6 8.5L9 3.75L12 8.5L16 5.75L15.25 13.25H2.75Z" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/><path d="M3.5 15.5H14.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>',
        'bolt' => '<path d="M9.75 2.25L3.75 10H8.25L7.75 15.75L14.25 7.5H9.75L9.75 2.25Z" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/>',
        'list' => '<path d="M6 4.5H15.25M6 9H15.25M6 13.5H15.25" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/><circle cx="3" cy="4.5" r="1" fill="currentColor"/><circle cx="3" cy="9" r="1" fill="currentColor"/><circle cx="3" cy="13.5" r="1" fill="currentColor"/>',
        'proxy' => '<circle cx="9" cy="4" r="1.75" stroke="currentColor" stroke-width="1.3"/><circle cx="4" cy="13.75" r="1.75" stroke="currentColor" stroke-width="1.3"/><circle cx="14" cy="13.75" r="1.75" stroke="currentColor" stroke-width="1.3"/><path d="M9 5.75V8.5M9 8.5L4.8 11.9M9 8.5L13.2 11.9" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/>',
        'upload' => '<path d="M9 11.5V2.75M9 2.75L5.75 6M9 2.75L12.25 6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/><path d="M2.75 12.75V14C2.75 14.83 3.42 15.5 4.25 15.5H13.75C14.58 15.5 15.25 14.83 15.25 14V12.75" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>',
        'star' => '<path d="M9 2.5L10.95 6.45L15.35 7.1L12.2 10.15L12.95 14.55L9 12.5L5.05 14.55L5.8 10.15L2.65 7.1L7.05 6.45L9 2.5Z" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/>',
        'ban' => '<circle cx="9" cy="9" r="6.5" stroke="currentColor" stroke-width="1.4"/><path d="M4.4 4.4L13.6 13.6" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>',
        'trash' => '<path d="M3.25 4.75H14.75" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/><path d="M7.25 4.75V3.5C7.25 3.09 7.59 2.75 8 2.75H10C10.41 2.75 10.75 3.09 10.75 3.5V4.75" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/><path d="M4.75 4.75L5.5 14C5.55 14.69 6.13 15.25 6.82 15.25H11.18C11.87 15.25 12.45 14.69 12.5 14L13.25 4.75" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/>',
        'play' => '<path d="M5.5 3.75L14.5 9L5.5 14.25V3.75Z" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/>',
        'stop' => '<rect x="4" y="4" width="10" height="10" rx="1.5" stroke="currentColor" stroke-width="1.4"/>',
        'refresh' => '<path d="M14.5 9C14.5 12.04 12.04 14.5 9 14.5C5.96 14.5 3.5 12.04 3.5 9C3.5 5.96 5.96 3.5 9 3.5C11.3 3.5 13.28 4.87 14.15 6.75" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/><path d="M14.5 3.25V7H10.75" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/>',
        'arrow-right' => '<path d="M2.75 9H15.25M15.25 9L11 4.75M15.25 9L11 13.25" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>',
    ];
    $body = $paths[$name] ?? $paths['info'];
    $cls = $class !== '' ? ' class="' . htmlspecialchars($class, ENT_QUOTES) . '"' : '';
    return '<svg xmlns="http://www.w3.org/2000/svg" width="' . $size . '" height="' . $size . '" viewBox="0 0 18 18" fill="none"' . $cls . ' style="display:inline-flex;vertical-align:middle;flex-shrink:0;">' . $body . '</svg>';
}

function Minhnhatdev_icon_toast(string $name): string {
    return Minhnhatdev_icon($name, '', 18);
}

function Minhnhatdev_icon_js(string $name, int $size = 18): string {
    return json_encode(Minhnhatdev_icon($name, '', $size));
}
