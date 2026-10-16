<script setup>
defineProps({
  name: { type: String, required: true },
  size: { type: Number, default: 15 },
})

/* 全部为内联 SVG 图标（stroke 风格），替代 emoji */
const ICONS = {
  dice: '<rect x="3.5" y="3.5" width="17" height="17" rx="3.5"/><circle cx="8.3" cy="8.3" r="1.5" fill="currentColor" stroke="none"/><circle cx="15.7" cy="8.3" r="1.5" fill="currentColor" stroke="none"/><circle cx="12" cy="12" r="1.5" fill="currentColor" stroke="none"/><circle cx="8.3" cy="15.7" r="1.5" fill="currentColor" stroke="none"/><circle cx="15.7" cy="15.7" r="1.5" fill="currentColor" stroke="none"/>',
  copy: '<rect x="9" y="9" width="12" height="12" rx="2.5"/><path d="M5 15H4.5A2.5 2.5 0 0 1 2 12.5v-8A2.5 2.5 0 0 1 4.5 2h8A2.5 2.5 0 0 1 15 4.5V5"/>',
  download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>',
  trash: '<path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/>',
  replay: '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/>',
  needle: '<line x1="19" y1="5" x2="9.5" y2="14.5"/><ellipse cx="7.8" cy="16.2" rx="2.1" ry="3.4" transform="rotate(45 7.8 16.2)"/><path d="M5.8 18.2 3 21"/>',
  spool: '<path d="M8 5V2.5h8V5M8 19v2.5h8V19"/><rect x="6" y="5" width="12" height="14" rx="1.5"/><path d="M9 9h6M9 12h6M9 15h6"/>',
  font: '<polyline points="5 19 11 5 17 19"/><line x1="7" y1="14" x2="15" y2="14"/><path d="M18 19c1.6 0 2.5-1 2.5-2.6V12"/>',
  flower: '<circle cx="12" cy="12" r="2.4"/><path d="M12 9.2V3.6M12 14.8v5.6M9.4 12H3.8M14.6 12h5.6M10.3 10.3 6.4 6.4M13.7 13.7l3.9 3.9M13.7 10.3l3.9-3.9M10.3 13.7l-3.9 3.9"/>',
  paste: '<rect x="5" y="5" width="14" height="17" rx="2"/><path d="M9 5a3 3 0 0 1 6 0"/><rect x="9" y="2.6" width="6" height="4" rx="1.2"/><path d="M9 12h6M9 16h6"/>',
  scissors: '<circle cx="6" cy="6" r="2.6"/><circle cx="6" cy="18" r="2.6"/><line x1="20" y1="4" x2="8.2" y2="15.8"/><line x1="14.6" y1="14.6" x2="20" y2="20"/><line x1="8.2" y1="8.2" x2="12" y2="12"/>',
}
</script>

<template>
  <!-- eslint-disable-next-line vue/no-v-html -->
  <svg
    :width="size" :height="size" viewBox="0 0 24 24" fill="none"
    stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
    aria-hidden="true" v-html="ICONS[name]"
  ></svg>
</template>
