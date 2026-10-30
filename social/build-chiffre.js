// Africa Music Radar · Le Chiffre de la semaine · génère 5 slides FR + 5 EN en SVG puis PNG 1080x1350
const fs = require('fs');
const path = require('path');
const d3 = require('d3-geo');
const topo = require('topojson-client');
const { Resvg } = require('@resvg/resvg-js');

const W = 1080, H = 1350;
const OUT = process.argv[2] || 'out';
fs.mkdirSync(OUT, { recursive: true });

const C = { paper:'#F5F2EC', ink:'#131211', muted:'#5A554C', rule:'#D3CCC0', red:'#C8201A', redDark:'#FF4B3E',
  amber:'#F2A71B', night:'#0B0B0C', nightText:'#F5F2EC', nightMuted:'#A8A094',
  landNight:'#24221F', strokeNight:'#3B3832', landPaper:'#E2DBCE', strokePaper:'#F5F2EC' };
const F = { serif:"AMR Serif", sans:"AMR Sans", mono:"AMR Mono" };

// ---------- carte ----------
const world = require('world-atlas/countries-50m.json');
const all = topo.feature(world, world.objects.countries).features;
const notAfrica = new Set(['Saudi Arabia','Yemen','Oman','United Arab Emirates','Qatar','Israel','Jordan','Iraq','Syria','Lebanon','Palestine','Kuwait','Bahrain','Iran','Turkey','Cyprus','N. Cyprus','Spain','Portugal','Italy','Greece','Malta','France','Gibraltar']);
const africa = all.filter(f => {
  if (notAfrica.has(f.properties.name)) return false;
  const [lon, lat] = d3.geoCentroid(f);
  return lon > -26 && lon < 58 && lat > -37 && lat < 38;
});
const fc = { type:'FeatureCollection', features: africa };
const byName = n => africa.find(f => f.properties.name === n);

function mapLayer(box, opts) {
  const proj = d3.geoMercator().fitExtent([[box[0], box[1]], [box[2], box[3]]], fc);
  const p = d3.geoPath(proj);
  const hi = opts.highlight || {};
  let s = '';
  for (const f of africa) {
    const h = hi[f.properties.name];
    s += `<path d="${p(f)}" fill="${h ? h.fill : opts.land}" stroke="${h && h.stroke ? h.stroke : opts.stroke}" stroke-width="${h && h.sw ? h.sw : 1.4}" ${h && h.dash ? `stroke-dasharray="${h.dash}"` : ''} stroke-linejoin="round"/>`;
  }
  return { svg: s, proj, path: p };
}

// ---------- helpers ----------
const esc = t => t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
function lines(arr, x, y, size, lh, attrs) {
  return arr.map((t, i) => `<text x="${x}" y="${y + i * lh}" font-size="${size}" ${attrs}>${esc(t)}</text>`).join('');
}
const mono = (t, x, y, size, fill, extra='') =>
  `<text x="${x}" y="${y}" font-family="${F.mono}" font-weight="500" font-size="${size}" letter-spacing="${size*0.08}" fill="${fill}" ${extra}>${esc(t.toUpperCase())}</text>`;

function chrome(theme, idx, label) {
  // logo + étiquette de série + barre de progression : identique sur toutes les slides
  const t = theme;
  let s = `<text x="80" y="104" font-family="${F.mono}" font-weight="600" font-size="26" letter-spacing="2.1" fill="${t.text}">AFRICA MUSIC <tspan fill="${t.logoRed}">RADAR</tspan></text>`;
  const lw = label.length * 16.2 + 40;
  s += `<rect x="${W-80-lw}" y="70" width="${lw}" height="48" rx="24" fill="none" stroke="${t.pill}" stroke-width="2"/>`;
  s += `<circle cx="${W-80-lw+22}" cy="94" r="7" fill="${t.ping}"/>`;
  s += mono(label, W-80-lw+38, 102, 22, t.pill);
  for (let i = 0; i < 5; i++) {
    const segW = (W - 160 - 4*10) / 5;
    s += `<rect x="${80 + i*(segW+10)}" y="146" width="${segW}" height="7" fill="${t.text}" opacity="${i <= idx ? 1 : 0.2}"/>`;
  }
  return s;
}

function radar(cx, cy, rMax, color, n, sweep) {
  let s = '';
  for (let i = 1; i <= n; i++) s += `<circle cx="${cx}" cy="${cy}" r="${rMax*i/n}" fill="none" stroke="${color}" stroke-width="2" opacity="${0.75 - i*0.1}"/>`;
  s += `<line x1="${cx-rMax}" y1="${cy}" x2="${cx+rMax}" y2="${cy}" stroke="${color}" stroke-width="1.2" opacity=".35"/>`;
  s += `<line x1="${cx}" y1="${cy-rMax}" x2="${cx}" y2="${cy+rMax}" stroke="${color}" stroke-width="1.2" opacity=".35"/>`;
  if (sweep) {
    const a0 = -95 * Math.PI/180, a1 = -40 * Math.PI/180;
    const x0 = cx + rMax*Math.cos(a0), y0 = cy + rMax*Math.sin(a0), x1 = cx + rMax*Math.cos(a1), y1 = cy + rMax*Math.sin(a1);
    s += `<path d="M${cx},${cy} L${x0},${y0} A${rMax},${rMax} 0 0 1 ${x1},${y1} Z" fill="url(#sweep)"/>`;
    s += `<line x1="${cx}" y1="${cy}" x2="${x1}" y2="${y1}" stroke="${color}" stroke-width="3"/>`;
  }
  return s;
}

const NIGHT = { bg:C.night, text:C.nightText, logoRed:C.redDark, pill:C.amber, ping:C.amber };
const PAPER = { bg:C.paper, text:C.ink, logoRed:C.red, pill:C.red, ping:C.red };
const AMBER = { bg:C.amber, text:C.ink, logoRed:C.red, pill:C.ink, ping:C.red };

function wrap(theme, body, idx, label, defs='') {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">
<defs>
<linearGradient id="sweep" x1="0" y1="1" x2="1" y2="0"><stop offset="0" stop-color="${C.redDark}" stop-opacity="0"/><stop offset="1" stop-color="${C.redDark}" stop-opacity=".45"/></linearGradient>
<linearGradient id="fadeB" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${theme.bg}" stop-opacity="0"/><stop offset="1" stop-color="${theme.bg}" stop-opacity="1"/></linearGradient>
${defs}
</defs>
<rect width="${W}" height="${H}" fill="${theme.bg}"/>
${body}
${chrome(theme, idx, label)}
</svg>`;
}

// ---------- contenus ----------
const T = {
  fr: {
    series:'Le Chiffre · 31.10',
    s1:{ credit:"Franck-Alcide Kacou, DG d'Universal Music Africa", sub:'sur 22', l1:["Sur les 22 pays d'Universal Music Africa,", "YouTube ne paie la musique que dans un seul."], swipe:'Lequel ?' },
    s2:{ k:'La réponse', h:['Le Sénégal.'], p:["Seul pays du réseau Universal où", "YouTube monétise la musique."], src:"Selon Franck-Alcide Kacou, DG d'Universal Music Africa", tag:'SÉNÉGAL' },
    s3:{ k:'Les 21 autres', h:['Des millions de vues.', 'Pas de monétisation', 'YouTube.'] },
    s4:{ k:'Ça bouge', h:["Meta avance en", "Côte d'Ivoire."], p:["Après le lobbying d'Universal et du", "ministère ivoirien de la Culture."], tag:'EN COURS' },
    s5:{ k:'À vous', h:['Vos vues YouTube', "viennent d'où ?"], p:['Répondez en commentaire.', 'La newsletter chaque semaine, lien en bio.'], src:'Source : Stratégies, interview de F.-A. Kacou, 29.10.2026' },
  },
  en: {
    series:'Figure · 31.10',
    s1:{ credit:'Franck-Alcide Kacou, MD of Universal Music Africa', sub:'in 22', l1:["Across Universal Music Africa's 22 countries,", "YouTube pays for music in just one."], swipe:'Which one?' },
    s2:{ k:'The answer', h:['Senegal.'], p:["The only country in Universal's network", "where YouTube monetises music."], src:"Per Franck-Alcide Kacou, MD of Universal Music Africa", tag:'SENEGAL' },
    s3:{ k:'The other 21', h:['Millions of views.', 'No YouTube', 'monetisation.'] },
    s4:{ k:'Things are moving', h:["Meta is moving in", "Côte d'Ivoire."], p:["After lobbying by Universal and", "Côte d'Ivoire's Ministry of Culture."], tag:'IN PROGRESS' },
    s5:{ k:'Your turn', h:['Where do your YouTube', 'views come from?'], p:['Tell us in the comments.', 'The newsletter every week, link in bio.'], src:'Source: Stratégies, interview with F.-A. Kacou, 29.10.2026' },
  }
};

const cities = [['Bamako',-8.0,12.65],['Abidjan',-4.03,5.36],['Lomé',1.22,6.13],['Douala',9.7,4.05],['Kinshasa',15.31,-4.32],['Antananarivo',47.52,-18.88]];

function slides(lang) {
  const t = T[lang];
  const out = [];

  // 1 · couverture : identité de série, carte + radar centré sur le Sénégal
  {
    const m = mapLayer([200, 230, 1030, 1000], { land:C.landNight, stroke:C.strokeNight, highlight:{ 'Senegal':{ fill:C.amber, stroke:C.amber } } });
    const [sx, sy] = m.proj([-14.8, 14.4]);
    let b = radar(sx, sy, 300, C.redDark, 4, true) + m.svg;
    b += `<circle cx="${sx}" cy="${sy}" r="12" fill="${C.amber}"/><circle cx="${sx}" cy="${sy}" r="26" fill="none" stroke="${C.amber}" stroke-width="3"/>`;
    b += `<rect x="0" y="760" width="${W}" height="${H-760}" fill="url(#fadeB)"/>`;
    b += `<text x="64" y="1150" font-family="${F.serif}" font-weight="700" font-size="400" letter-spacing="-14" fill="${C.amber}">1</text>`;
    b += `<text x="335" y="1150" font-family="${F.serif}" font-weight="600" font-size="130" letter-spacing="-3" fill="${C.nightText}">${esc(t.s1.sub)}</text>`;
    b += lines(t.s1.l1, 80, 1218, 38, 50, `font-family="${F.sans}" font-weight="600" fill="${C.nightText}"`);
    b += mono(t.s1.swipe, 80, 1300, 24, C.amber);
    { const ax = 80 + t.s1.swipe.length*16.2 + 18; b += `<line x1="${ax}" y1="1292" x2="${ax+56}" y2="1292" stroke="${C.amber}" stroke-width="3"/><path d="M${ax+44},1282 L${ax+58},1292 L${ax+44},1302" fill="none" stroke="${C.amber}" stroke-width="3"/>`; }
    out.push(wrap(NIGHT, b, 0, t.series));
  }

  // 1 bis · couverture photo (si une photo est fournie) : photo en haut, chiffre + mini carte radar en bas
  if (process.env.PHOTO) {
    const data = 'data:image/' + (process.env.PHOTO.endsWith('.png') ? 'png' : 'jpeg') + ';base64,' + fs.readFileSync(process.env.PHOTO).toString('base64');
    const defs = `<linearGradient id="topShade" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${C.night}" stop-opacity=".75"/><stop offset="1" stop-color="${C.night}" stop-opacity="0"/></linearGradient>
<linearGradient id="photoFade" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${C.night}" stop-opacity="0"/><stop offset="1" stop-color="${C.night}" stop-opacity="1"/></linearGradient>`;
    let b = `<image href="${data}" x="-40" y="0" width="${W+80}" height="980" preserveAspectRatio="xMidYMid slice"/>`;
    b += `<rect x="0" y="0" width="${W}" height="220" fill="url(#topShade)"/>`;
    b += `<rect x="0" y="640" width="${W}" height="342" fill="url(#photoFade)"/>`;
    b += mono(t.s1.credit, 80, 905, 19, C.nightMuted);
    // mini carte + radar, signature de la série
    const m = mapLayer([790, 950, 1010, 1170], { land:'#2E2B27', stroke:C.night, highlight:{ 'Senegal':{ fill:C.amber, stroke:C.amber } } });
    const [sx, sy] = m.proj([-14.8, 14.4]);
    b += radar(sx, sy, 120, C.redDark, 3, true) + m.svg + `<circle cx="${sx}" cy="${sy}" r="6" fill="${C.amber}"/>`;
    b += `<text x="64" y="1150" font-family="${F.serif}" font-weight="700" font-size="300" letter-spacing="-10" fill="${C.amber}">1</text>`;
    b += `<text x="270" y="1150" font-family="${F.serif}" font-weight="600" font-size="110" letter-spacing="-3" fill="${C.nightText}">${esc(t.s1.sub)}</text>`;
    b += lines(t.s1.l1, 80, 1218, 38, 50, `font-family="${F.sans}" font-weight="600" fill="${C.nightText}"`);
    b += mono(t.s1.swipe, 80, 1300, 24, C.amber);
    { const ax = 80 + t.s1.swipe.length*16.2 + 18; b += `<line x1="${ax}" y1="1292" x2="${ax+56}" y2="1292" stroke="${C.amber}" stroke-width="3"/><path d="M${ax+44},1282 L${ax+58},1292 L${ax+44},1302" fill="none" stroke="${C.amber}" stroke-width="3"/>`; }
    out[0] = wrap(NIGHT, b, 0, t.series, defs);
  }

  // 2 · la réponse : carte papier, Sénégal surligné avec étiquette
  {
    const m = mapLayer([210, 330, 1020, 1090], { land:C.landPaper, stroke:C.strokePaper, highlight:{ 'Senegal':{ fill:C.amber, stroke:C.ink, sw:3 } } });
    const [sx, sy] = m.proj([-14.8, 14.4]);
    let b = m.svg;
    b += `<circle cx="${sx}" cy="${sy}" r="40" fill="none" stroke="${C.ink}" stroke-width="3"/>`;
    b += `<line x1="${sx-40}" y1="${sy}" x2="80" y2="${sy}" stroke="${C.ink}" stroke-width="3"/>`;
    b += `<rect x="80" y="${sy-56}" width="${t.s2.tag.length*19+40}" height="44" fill="${C.ink}"/>`;
    b += mono(t.s2.tag, 100, sy-25, 24, C.amber);
    b += mono(t.s2.k, 80, 230, 24, C.red);
    b += lines(t.s2.h, 76, 320, 104, 104, `font-family="${F.serif}" font-weight="600" letter-spacing="-2" fill="${C.ink}"`);
    b += lines(t.s2.p, 80, 1170, 40, 52, `font-family="${F.sans}" font-weight="600" fill="${C.ink}"`);
    b += mono(t.s2.src, 80, 1296, 19, C.muted);
    out.push(wrap(PAPER, b, 1, t.series));
  }

  // 3 · les 21 autres : carte nuit, villes en points rouges
  {
    const m = mapLayer([170, 470, 1010, 1280], { land:C.landNight, stroke:C.strokeNight, highlight:{ 'Senegal':{ fill:C.amber, stroke:C.amber } } });
    let b = m.svg;
    for (const [n, lon, lat] of cities) {
      const [x, y] = m.proj([lon, lat]);
      b += `<circle cx="${x}" cy="${y}" r="22" fill="${C.redDark}" opacity=".25"/><circle cx="${x}" cy="${y}" r="10" fill="${C.redDark}"/>`;
      const right = !['Antananarivo','Abidjan'].includes(n);
      if (n === 'Lomé') b += mono(n, x, y + 44, 21, C.nightText, 'text-anchor="middle"');
      else b += mono(n, right ? x + 26 : x - 26, y + 8, 21, C.nightText, right ? '' : 'text-anchor="end"');
    }
    b += mono(t.s3.k, 80, 230, 24, C.redDark);
    b += lines(t.s3.h, 76, 320, 80, 86, `font-family="${F.serif}" font-weight="600" letter-spacing="-1.5" fill="${C.nightText}"`);
    out.push(wrap(NIGHT, b, 2, t.series));
  }

  // 4 · ça bouge : Côte d'Ivoire en pointillés rouges
  {
    const m = mapLayer([260, 470, 1020, 1210], { land:C.landPaper, stroke:C.strokePaper, highlight:{
      'Senegal':{ fill:C.amber, stroke:C.ink, sw:2 }, "Côte d'Ivoire":{ fill:'#F3C9C2', stroke:C.red, sw:5, dash:'10 7' } } });
    const [cx, cy] = m.proj([-5.5, 7.6]);
    let b = m.svg;
    b += `<line x1="${cx}" y1="${cy}" x2="${cx}" y2="${cy+170}" stroke="${C.red}" stroke-width="3"/>`;
    const tw = t.s4.tag.length*19+40;
    b += `<rect x="${cx-20}" y="${cy+170}" width="${tw}" height="46" fill="${C.red}"/>`;
    b += mono(t.s4.tag, cx, cy+201, 24, '#FFFFFF');
    b += mono(t.s4.k, 80, 230, 24, C.red);
    b += lines(t.s4.h, 76, 330, 96, 100, `font-family="${F.serif}" font-style="italic" font-weight="500" letter-spacing="-1.5" fill="${C.ink}"`);
    b += lines(t.s4.p, 80, 1250, 34, 46, `font-family="${F.sans}" font-weight="400" fill="${C.muted}"`);
    out.push(wrap(PAPER, b, 3, t.series));
  }

  // 5 · question : radar plein cadre, point d'interrogation au centre
  {
    let b = radar(W/2, 760, 360, C.ink, 4, false);
    b += `<circle cx="${W/2}" cy="760" r="120" fill="${C.ink}"/>`;
    b += `<text x="${W/2}" y="830" text-anchor="middle" font-family="${F.serif}" font-weight="700" font-size="200" fill="${C.amber}">?</text>`;
    b += mono(t.s5.k, 80, 230, 24, C.ink);
    b += lines(t.s5.h, 76, 320, 84, 90, `font-family="${F.serif}" font-weight="600" letter-spacing="-1.5" fill="${C.ink}"`);
    b += lines(t.s5.p, 80, 1196, 34, 46, `font-family="${F.sans}" font-weight="600" fill="${C.ink}"`);
    b += mono(t.s5.src, 80, 1300, 19, C.ink);
    out.push(wrap(AMBER, b, 4, t.series));
  }
  return out;
}

const fontFiles = fs.readdirSync(path.join(__dirname, 'fonts')).map(f => path.join(__dirname, 'fonts', f));
for (const lang of ['fr', 'en']) {
  slides(lang).forEach((svg, i) => {
    const base = path.join(OUT, `chiffre-2026-10-31-${lang}-${i+1}`);
    fs.writeFileSync(base + '.svg', svg);
    const png = new Resvg(svg, { font: { fontFiles, loadSystemFonts: false, defaultFontFamily: F.sans }, fitTo: { mode: 'width', value: W } }).render().asPng();
    fs.writeFileSync(base + '.png', png);
  });
}
console.log('ok', africa.length, 'pays');
