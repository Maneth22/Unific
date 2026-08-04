// Single source of truth for responsive breakpoints used by
// useCollapsibleSidebar's matchMedia queries. Mirrored as a comment in
// tokens.css (media-query bounds can't reference CSS custom properties,
// so keep both in sync by hand if these ever change).
export const BREAKPOINTS = {
  mobile: 767, // <=767px: hidden sidebar + hamburger + full-screen drawer
  tablet: 1023, // 768-1023px: auto-collapsed slim tab by default
}
