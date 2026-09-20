import { HOME_HTML } from "./shell.generated";

// The original Home markup, verbatim, with the sample-data blocks turned into
// mount points for REAL backend data (see PlanBoundApp / HomeLive / HomeBelow).
let html = HOME_HTML;

// The approved site replaces the v1 paths and static tiles with live sections.
html = html.replace(
  /<section class="paths reveal" id="paths">[\s\S]*?<\/section>\s*<section class="section reveal" id="signals">[\s\S]*?<\/section>\s*<section class="review"/,
  '<div id="home-below-root"></div>\n\n<section class="review"',
);
// The demo Plan Review (sample S3/SG/IAM changes) becomes the real "latest plan" mount.
html = html.replace(
  /<section class="review" id="review">[\s\S]*?<\/section>\s*<section class="section about/,
  '<section class="review" id="review"><div id="home-live-root"></div></section>\n\n<section class="section about',
);

export const HOME_MARKUP = html;
