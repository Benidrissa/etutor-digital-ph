/**
 * A scene's backdrop: the course's generated picture of the place (3:2,
 * slowly panned across the 4:3 stage), or a painted placeholder in the
 * Scratch prototype's style — a gradient sky over orange laterite, or a wall
 * over a floor indoors — with a few props that say where we are, and cheap
 * ambient motion: drifting clouds and a bird.
 *
 * Everything that moves is an HTML layer moved by `transform`, which the
 * compositor runs without repainting the picture underneath.
 */

import { memo, useState, type CSSProperties, type ReactNode } from "react";

import { hashOf } from "./cast";
import { INDOOR, skyFor, type PlaceTheme, type SkyMood } from "./places";
import styles from "./stage.module.css";

const O = "#3b2418";

interface BackdropProps {
  placeId: string;
  theme: PlaceTheme;
  /** The generated backdrop, when the course has one. */
  url?: string;
}

function BackdropView({ placeId, theme, url }: BackdropProps) {
  const [failed, setFailed] = useState<string | null>(null);
  if (url && failed !== url) {
    return (
      <div className="absolute inset-0 overflow-hidden bg-[#f6d7b0]" aria-hidden="true">
        {/* 12% wider than the stage, the extra width of a 3:2 picture. */}
        <div className={`absolute inset-y-0 left-0 w-[112%] ${styles.pan}`}>
          {/* eslint-disable-next-line @next/next/no-img-element -- a same-origin API image, sized by CSS */}
          <img
            src={url}
            alt=""
            className="h-full w-full object-cover"
            onError={() => setFailed(url)}
            draggable={false}
          />
        </div>
      </div>
    );
  }
  return <PlaceholderBackdrop placeId={placeId} theme={theme} />;
}

/* -------------------------------------------------------------------------- */

const SKIES: Record<SkyMood, [string, string, string]> = {
  dawn: ["#ffb59e", "#ffd1a8", "#ffe6bf"],
  day: ["#7fc8f0", "#bfe6fb", "#e8f7ff"],
  evening: ["#c98bb9", "#f6a77a", "#fbd49c"],
};

/** Speckles on the ground, at fixed spots per place. */
function speckles(placeId: string, color: string, top: number) {
  let seed = hashOf(placeId) || 1;
  const next = () => {
    seed = (seed * 16807) % 2147483647;
    return seed / 2147483647;
  };
  return Array.from({ length: 22 }, (_, i) => (
    <circle key={i} cx={next() * 480} cy={top + 8 + next() * (352 - top)} r={1 + next() * 2.6} fill={color} opacity="0.45" />
  ));
}

function PlaceholderBackdrop({ placeId, theme }: { placeId: string; theme: PlaceTheme }) {
  const indoor = INDOOR.has(theme);
  const sky = SKIES[skyFor(placeId)];
  const uid = `bd-${hashOf(placeId)}`;
  return (
    <div className="absolute inset-0" aria-hidden="true">
    <svg
      viewBox="0 0 480 360"
      preserveAspectRatio="xMidYMid slice"
      className="absolute inset-0 h-full w-full"
      focusable="false"
    >
      <defs>
        <linearGradient id={`${uid}-sky`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={sky[0]} />
          <stop offset="0.55" stopColor={sky[1]} />
          <stop offset="1" stopColor={sky[2]} />
        </linearGradient>
        <linearGradient id={`${uid}-ground`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={theme === "farm" ? "#8cc152" : "#e2803f"} />
          <stop offset="1" stopColor={theme === "farm" ? "#5e9a32" : "#c45f2a"} />
        </linearGradient>
        <linearGradient id={`${uid}-wall`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={WALLS[theme]?.[0] ?? "#f6e7c8"} />
          <stop offset="1" stopColor={WALLS[theme]?.[1] ?? "#ecd6aa"} />
        </linearGradient>
      </defs>
      {indoor ? <Indoor theme={theme} uid={uid} /> : <Outdoor theme={theme} uid={uid} placeId={placeId} mood={skyFor(placeId)} />}
    </svg>
    {indoor ? null : <AmbientSky />}
    </div>
  );
}

const WALLS: Partial<Record<PlaceTheme, [string, string]>> = {
  classroom: ["#f6e7c8", "#ecd6aa"],
  kitchen: ["#fdf1dc", "#f4dfba"],
  desk: ["#e9eefb", "#d6def3"],
  office: ["#e6f0ef", "#cfe0de"],
  lab: ["#eaf4fb", "#d3e6f3"],
};

/* ---- Outdoor ------------------------------------------------------------- */

function Outdoor({
  theme,
  uid,
  placeId,
  mood,
}: {
  theme: PlaceTheme;
  uid: string;
  placeId: string;
  mood: SkyMood;
}) {
  const horizon = 270;
  const sunX = mood === "day" ? 400 : mood === "dawn" ? 96 : 360;
  const sunY = mood === "day" ? 58 : 150;
  return (
    <g>
      <rect width="480" height="360" fill={`url(#${uid}-sky)`} />
      <circle cx={sunX} cy={sunY} r="46" fill="#fff3b0" opacity="0.45" />
      <circle cx={sunX} cy={sunY} r="28" fill={mood === "evening" ? "#ffb347" : "#ffd36b"} />
      {/* Far hills. */}
      <path
        d={`M0,${horizon - 18} Q60,${horizon - 44} 130,${horizon - 22} T270,${horizon - 26} T400,${horizon - 30} T480,${horizon - 20} L480,${horizon + 4} L0,${horizon + 4} Z`}
        fill={theme === "farm" ? "#9fcf7a" : "#e9a774"}
        opacity="0.75"
      />
      <Props theme={theme} horizon={horizon} />
      {/* The ground. */}
      <path d={`M0,${horizon} Q240,${horizon - 8} 480,${horizon} L480,360 L0,360 Z`} fill={`url(#${uid}-ground)`} />
      {theme === "road" ? <Road horizon={horizon} /> : null}
      {speckles(placeId, theme === "farm" ? "#3f6f22" : "#9c4a1d", horizon)}
      <ForegroundProps theme={theme} horizon={horizon} />
    </g>
  );
}

const CLOUDS: Array<{ top: string; width: string; seconds: string; delay: string }> = [
  { top: "9%", width: "19%", seconds: "80s", delay: "-20s" },
  { top: "25%", width: "13%", seconds: "120s", delay: "-75s" },
  { top: "5%", width: "10%", seconds: "95s", delay: "-50s" },
];

/** Clouds and a bird crossing the sky: HTML layers, moved by transform. */
function AmbientSky() {
  return (
    <>
      {CLOUDS.map((cloud, i) => (
        <div
          key={i}
          className={`${styles.drift} absolute inset-x-0`}
          style={{ top: cloud.top, "--drift-s": cloud.seconds, "--drift-delay": cloud.delay } as CSSProperties}
        >
          <svg viewBox="0 0 90 40" style={{ width: cloud.width, opacity: 0.9 }} focusable="false">
            <ellipse cx="40" cy="18" rx="28" ry="15" fill="#fff" />
            <ellipse cx="66" cy="22" rx="22" ry="12" fill="#fff" />
            <ellipse cx="20" cy="24" rx="18" ry="10" fill="#fff" />
            <rect x="10" y="22" width="72" height="12" rx="6" fill="#fff" />
          </svg>
        </div>
      ))}
      <div className={`${styles.fly} absolute inset-x-0 top-[30%]`} style={{ "--fly-delay": "-6s" } as CSSProperties}>
        <svg viewBox="0 0 60 20" style={{ width: "7%" }} focusable="false">
          <path d="M2,10 Q8,4 14,10 Q20,4 26,10" stroke="#3b2a2a" strokeWidth="2.2" fill="none" strokeLinecap="round" />
          <path d="M34,6 Q38,2 42,6 Q46,2 50,6" stroke="#3b2a2a" strokeWidth="1.8" fill="none" strokeLinecap="round" />
        </svg>
      </div>
    </>
  );
}

function Baobab({ x, base, scale = 1, opacity = 1 }: { x: number; base: number; scale?: number; opacity?: number }) {
  return (
    <g transform={`translate(${x},${base}) scale(${scale})`} opacity={opacity}>
      <path d="M-14,0 Q-16,-50 -10,-78 L10,-78 Q16,-50 14,0 Z" fill="#a07a5f" />
      {[-34, -18, 0, 18, 34].map((dx, i) => (
        <path key={i} d={`M${dx / 4},-74 Q${dx * 0.6},-92 ${dx},${-104 + Math.abs(dx) * 0.2}`} stroke="#a07a5f" strokeWidth="6" strokeLinecap="round" fill="none" />
      ))}
    </g>
  );
}

function MangoTree({ x, base, scale = 1 }: { x: number; base: number; scale?: number }) {
  return (
    <g transform={`translate(${x},${base}) scale(${scale})`}>
      <path d="M-7,0 L-5,-56 L5,-56 L7,0 Z" fill="#7b5032" stroke={O} strokeWidth="2" />
      <circle cx="-26" cy="-70" r="26" fill="#3f8f5a" stroke={O} strokeWidth="2" />
      <circle cx="24" cy="-72" r="27" fill="#3f8f5a" stroke={O} strokeWidth="2" />
      <circle cx="0" cy="-96" r="30" fill="#4fa86a" stroke={O} strokeWidth="2" />
      <circle cx="0" cy="-66" r="24" fill="#58b574" />
      {[
        [-24, -64],
        [14, -92],
        [26, -66],
        [-8, -82],
        [-30, -86],
      ].map(([mx, my], i) => (
        <ellipse key={i} cx={mx} cy={my} rx="5" ry="6.5" fill="#ffc94a" stroke={O} strokeWidth="1.4" />
      ))}
    </g>
  );
}

function Stall({ x, base, color }: { x: number; base: number; color: string }) {
  return (
    <g transform={`translate(${x},${base})`}>
      <rect x="-40" y="-70" width="5" height="70" fill="#7b5032" />
      <rect x="35" y="-70" width="5" height="70" fill="#7b5032" />
      <rect x="-44" y="-34" width="88" height="14" rx="2" fill="#b07a4f" stroke={O} strokeWidth="1.6" />
      {[0, 1, 2, 3, 4, 5].map((n) => (
        <circle key={n} cx={-34 + n * 13.5} cy="-38" r="5.5" fill={["#ff9f1c", "#e63946", "#ffd23f", "#8cc152", "#ff9f1c", "#e63946"][n]} stroke={O} strokeWidth="1" />
      ))}
      <path d="M-48,-70 L48,-70 L44,-88 L-44,-88 Z" fill="#fff8ec" stroke={O} strokeWidth="1.6" />
      {[0, 1, 2, 3, 4, 5].map((n) => (
        <path key={n} d={`M${-44 + n * 16},-88 L${-32 + n * 16},-88 L${-30 + n * 16},-70 L${-46 + n * 16},-70 Z`} fill={n % 2 ? color : "#fff8ec"} opacity={n % 2 ? 1 : 0} />
      ))}
      <path d="M-48,-70 Q-40,-62 -32,-70 Q-24,-62 -16,-70 Q-8,-62 0,-70 Q8,-62 16,-70 Q24,-62 32,-70 Q40,-62 48,-70" fill={color} stroke={O} strokeWidth="1.4" />
    </g>
  );
}

function House({ x, base }: { x: number; base: number }) {
  return (
    <g transform={`translate(${x},${base})`}>
      <rect x="-70" y="-90" width="140" height="90" fill="#e0905a" stroke={O} strokeWidth="2" />
      <path d="M-82,-88 L0,-140 L82,-88 Z" fill="#8a5a3c" stroke={O} strokeWidth="2" strokeLinejoin="round" />
      <path d="M-60,-82 L-50,-74 L-40,-82 L-30,-74 L-20,-82 L-10,-74 L0,-82 L10,-74 L20,-82 L30,-74 L40,-82 L50,-74 L60,-82" stroke="#fff" strokeWidth="2" fill="none" />
      <rect x="-14" y="-52" width="28" height="52" rx="3" fill="#7b4a2a" stroke={O} strokeWidth="1.8" />
      <rect x="-56" y="-60" width="26" height="22" fill="#9fd3f2" stroke="#fff" strokeWidth="3" />
      <rect x="30" y="-60" width="26" height="22" fill="#9fd3f2" stroke="#fff" strokeWidth="3" />
    </g>
  );
}

function Hut({ x, base, scale = 1 }: { x: number; base: number; scale?: number }) {
  return (
    <g transform={`translate(${x},${base}) scale(${scale})`}>
      <rect x="-30" y="-44" width="60" height="44" fill="#c9824c" stroke={O} strokeWidth="2" />
      <path d="M-40,-40 L0,-82 L40,-40 Z" fill="#d9b36a" stroke={O} strokeWidth="2" strokeLinejoin="round" />
      <path d="M-30,-48 L-14,-62 M-8,-46 L6,-66 M14,-48 L24,-58" stroke="#a9843f" strokeWidth="2" />
      <path d="M-9,0 L-9,-24 Q0,-32 9,-24 L9,0 Z" fill="#5c3a22" />
    </g>
  );
}

function Building({ x, base, cross }: { x: number; base: number; cross?: boolean }) {
  return (
    <g transform={`translate(${x},${base})`}>
      <rect x="-110" y="-96" width="220" height="96" fill={cross ? "#f7f4ee" : "#f2d7a7"} stroke={O} strokeWidth="2" />
      <rect x="-118" y="-104" width="236" height="12" fill={cross ? "#2a9d8f" : "#c0603a"} stroke={O} strokeWidth="2" />
      {[-90, -54, 30, 66].map((wx) => (
        <rect key={wx} x={wx} y="-74" width="26" height="24" fill="#9fd3f2" stroke={O} strokeWidth="1.6" />
      ))}
      <rect x="-16" y="-60" width="32" height="60" fill="#6b4a2f" stroke={O} strokeWidth="1.8" />
      {cross ? (
        <g transform="translate(0,-120)">
          <rect x="-16" y="-16" width="32" height="32" rx="4" fill="#fff" stroke={O} strokeWidth="2" />
          <path d="M-4,-11 L4,-11 L4,-4 L11,-4 L11,4 L4,4 L4,11 L-4,11 L-4,4 L-11,4 L-11,-4 L-4,-4 Z" fill="#2fa84f" />
        </g>
      ) : (
        <g transform="translate(150,0)">
          <rect x="-2" y="-130" width="4" height="130" fill="#6b6b6b" />
          <path d="M2,-128 L40,-120 L2,-110 Z" fill="#2ec4b6" stroke={O} strokeWidth="1.4" />
        </g>
      )}
    </g>
  );
}

function Skyline({ horizon }: { horizon: number }) {
  const towers = [
    [10, 90],
    [60, 130],
    [110, 70],
    [150, 160],
    [210, 100],
    [260, 140],
    [320, 80],
    [370, 120],
    [420, 95],
  ];
  return (
    <g>
      {towers.map(([x, h], i) => (
        <g key={i}>
          <rect x={x} y={horizon - h} width="44" height={h} fill={i % 2 ? "#8aa1c1" : "#a9bcd6"} stroke={O} strokeWidth="1.4" />
          {Array.from({ length: Math.floor(h / 22) }, (_, row) => (
            <g key={row}>
              <rect x={x + 8} y={horizon - h + 10 + row * 22} width="9" height="10" fill="#fff6c8" />
              <rect x={x + 26} y={horizon - h + 10 + row * 22} width="9" height="10" fill="#fff6c8" />
            </g>
          ))}
        </g>
      ))}
    </g>
  );
}

function Props({ theme, horizon }: { theme: PlaceTheme; horizon: number }) {
  switch (theme) {
    case "market":
      return (
        <g>
          <Stall x={95} base={horizon + 6} color="#e63946" />
          <Stall x={240} base={horizon + 6} color="#2a9d8f" />
          <Stall x={385} base={horizon + 6} color="#8e44ad" />
        </g>
      );
    case "farm":
      return (
        <g>
          <MangoTree x={70} base={horizon + 4} scale={0.8} />
          <MangoTree x={250} base={horizon + 2} scale={0.6} />
          <MangoTree x={410} base={horizon + 4} scale={0.85} />
        </g>
      );
    case "home":
      return (
        <g>
          <House x={330} base={horizon + 4} />
          <MangoTree x={130} base={horizon + 4} scale={0.85} />
          <rect x="180" y={horizon - 10} width="56" height="8" rx="2" fill="#7b5032" stroke={O} strokeWidth="1.4" />
        </g>
      );
    case "yard":
      return (
        <g>
          <Building x={250} base={horizon + 2} />
          <MangoTree x={60} base={horizon + 4} scale={0.7} />
        </g>
      );
    case "clinic":
      return (
        <g>
          <Building x={260} base={horizon + 2} cross />
          <MangoTree x={58} base={horizon + 4} scale={0.65} />
        </g>
      );
    case "shop":
      return (
        <g>
          <g transform={`translate(260,${horizon + 2})`}>
            <rect x="-100" y="-110" width="200" height="110" fill="#f2c57c" stroke={O} strokeWidth="2" />
            <rect x="-86" y="-104" width="172" height="22" rx="3" fill="#2a9d8f" stroke={O} strokeWidth="1.6" />
            <rect x="-90" y="-70" width="72" height="50" fill="#9fd3f2" stroke={O} strokeWidth="1.6" />
            <rect x="10" y="-72" width="34" height="72" fill="#6b4a2f" stroke={O} strokeWidth="1.6" />
            <path d="M-104,-80 L104,-80 L96,-66 L-96,-66 Z" fill="#e63946" stroke={O} strokeWidth="1.4" />
          </g>
          <Baobab x={60} base={horizon + 4} scale={0.9} opacity={0.6} />
        </g>
      );
    case "city":
      return <Skyline horizon={horizon + 2} />;
    case "village":
      return (
        <g>
          <Hut x={300} base={horizon + 4} />
          <Hut x={390} base={horizon + 2} scale={0.8} />
          <Baobab x={110} base={horizon + 4} scale={1} opacity={0.7} />
        </g>
      );
    case "road":
      return (
        <g>
          <Baobab x={80} base={horizon + 2} scale={0.8} opacity={0.6} />
          <g transform={`translate(380,${horizon + 2})`}>
            <rect x="-2" y="-70" width="4" height="70" fill="#6b6b6b" />
            <rect x="-24" y="-92" width="48" height="26" rx="4" fill="#2b4ea2" stroke={O} strokeWidth="1.6" />
            <rect x="-14" y="-86" width="28" height="14" rx="2" fill="#fff" opacity="0.85" />
          </g>
        </g>
      );
    default:
      return (
        <g>
          <Baobab x={410} base={horizon + 6} scale={1.15} opacity={0.75} />
          <Baobab x={70} base={horizon + 4} scale={0.7} opacity={0.5} />
        </g>
      );
  }
}

function ForegroundProps({ theme, horizon }: { theme: PlaceTheme; horizon: number }) {
  if (theme === "village") {
    return (
      <g transform={`translate(200,${horizon + 22})`}>
        <ellipse cx="0" cy="0" rx="26" ry="9" fill="#9a8f84" stroke={O} strokeWidth="1.6" />
        <ellipse cx="0" cy="-2" rx="18" ry="5" fill="#3f6f99" />
      </g>
    );
  }
  if (theme === "farm") {
    return (
      <g opacity="0.7">
        {[40, 120, 200, 280, 360, 440].map((x) => (
          <path key={x} d={`M${x - 10},${horizon + 30} Q${x},${horizon + 14} ${x + 10},${horizon + 30}`} stroke="#3f6f22" strokeWidth="3" fill="none" />
        ))}
      </g>
    );
  }
  return null;
}

function Road({ horizon }: { horizon: number }) {
  return (
    <g>
      <path d={`M0,${horizon + 20} L480,${horizon + 14} L480,${horizon + 46} L0,${horizon + 54} Z`} fill="#5b5b60" />
      {[20, 120, 220, 320, 420].map((x) => (
        <rect key={x} x={x} y={horizon + 31 - x * 0.012} width="44" height="4" fill="#f5f0dc" />
      ))}
    </g>
  );
}

/* ---- Indoor -------------------------------------------------------------- */

function Indoor({ theme, uid }: { theme: PlaceTheme; uid: string }) {
  const floorTop = 262;
  return (
    <g>
      <rect width="480" height="360" fill={`url(#${uid}-wall)`} />
      <rect y={floorTop - 10} width="480" height="10" fill="#b98b5a" />
      <rect y={floorTop} width="480" height={360 - floorTop} fill={theme === "lab" || theme === "office" ? "#c9c3b8" : "#c9a46b"} />
      {Array.from({ length: 8 }, (_, i) => (
        <path key={i} d={`M${i * 64},${floorTop} L${i * 64 - 30},360`} stroke="#000" strokeOpacity="0.07" strokeWidth="2" />
      ))}
      <IndoorProps theme={theme} />
      <Clock x={theme === "classroom" ? 300 : 70} y={44} />
    </g>
  );
}

function Window({ x, y, w = 90, h = 80 }: { x: number; y: number; w?: number; h?: number }) {
  return (
    <g>
      <rect x={x} y={y} width={w} height={h} fill="#a8dcf5" stroke="#fff" strokeWidth="6" />
      <path d={`M${x + w / 2},${y} L${x + w / 2},${y + h} M${x},${y + h / 2} L${x + w},${y + h / 2}`} stroke="#fff" strokeWidth="5" />
      <rect x={x} y={y} width={w} height={h} fill="none" stroke={O} strokeWidth="1.6" />
    </g>
  );
}

function Clock({ x, y }: { x: number; y: number }) {
  return (
    <g transform={`translate(${x},${y})`}>
      <circle r="15" fill="#fff" stroke={O} strokeWidth="2.4" />
      <path d="M0,0 L0,-9" stroke={O} strokeWidth="2.4" strokeLinecap="round" />
      <path d="M0,0 L-4,-11" stroke="#c1272d" strokeWidth="1.4" strokeLinecap="round" />
      <path d="M0,0 L7,3" stroke={O} strokeWidth="2.4" strokeLinecap="round" />
    </g>
  );
}

function IndoorProps({ theme }: { theme: PlaceTheme }): ReactNode {
  switch (theme) {
    case "classroom":
      return (
        <g>
          <rect x="70" y="40" width="200" height="120" rx="4" fill="#2f6b4f" stroke="#9a6332" strokeWidth="9" />
          <path d="M92,72 Q120,62 150,74 M92,96 L190,96 M92,118 Q140,110 172,120" stroke="#fff" strokeOpacity="0.35" strokeWidth="2.4" fill="none" strokeLinecap="round" />
          <rect x="120" y="160" width="40" height="5" fill="#9a6332" />
          <Window x={350} y={60} />
          <rect x="356" y="160" width="76" height="52" rx="3" fill="#fffdf6" stroke={O} strokeWidth="1.6" />
          <path d="M364,174 L420,174 M364,186 L410,186 M364,198 L416,198" stroke="#c1272d" strokeWidth="2" />
          {[40, 190, 340].map((x) => (
            <rect key={x} x={x} y="236" width="100" height="14" rx="3" fill="#9a6332" stroke={O} strokeWidth="1.6" />
          ))}
        </g>
      );
    case "kitchen":
      return (
        <g>
          <Window x={190} y={50} w={100} h={80} />
          <rect x="40" y="110" width="110" height="10" fill="#9a6332" />
          <circle cx="70" cy="98" r="12" fill="#c0603a" stroke={O} strokeWidth="1.6" />
          <rect x="96" y="86" width="22" height="24" rx="3" fill="#2a9d8f" stroke={O} strokeWidth="1.6" />
          <rect x="330" y="170" width="120" height="80" rx="4" fill="#b07a4f" stroke={O} strokeWidth="2" />
          <ellipse cx="370" cy="166" rx="22" ry="8" fill="#6b6b6b" stroke={O} strokeWidth="1.6" />
        </g>
      );
    case "desk":
      return (
        <g>
          <Window x={300} y={50} w={110} h={90} />
          <rect x="20" y="40" width="110" height="80" fill="#fffdf6" stroke={O} strokeWidth="1.6" />
          <path d="M34,62 L116,62 M34,80 L100,80 M34,98 L110,98" stroke="#457b9d" strokeWidth="2" />
          <rect x="330" y="186" width="140" height="12" fill="#9a6332" stroke={O} strokeWidth="1.6" />
          <rect x="340" y="198" width="10" height="56" fill="#7b5032" />
          <rect x="450" y="198" width="10" height="56" fill="#7b5032" />
          <path d="M440,186 L430,150 L452,140" stroke={O} strokeWidth="3" fill="none" />
          <path d="M444,132 L466,142 L456,152 Z" fill="#ffd23f" stroke={O} strokeWidth="1.4" />
          <rect x="350" y="172" width="34" height="14" fill="#e63946" stroke={O} strokeWidth="1.2" />
          <rect x="354" y="160" width="30" height="12" fill="#2a9d8f" stroke={O} strokeWidth="1.2" />
        </g>
      );
    case "office":
      return (
        <g>
          <Window x={40} y={50} w={110} h={90} />
          <rect x="190" y="50" width="150" height="96" rx="3" fill="#ffffff" stroke={O} strokeWidth="2" />
          <path d="M206,124 L230,96 L254,110 L282,76 L320,88" stroke="#2a9d8f" strokeWidth="3" fill="none" />
          <rect x="390" y="150" width="60" height="100" rx="3" fill="#8d99ae" stroke={O} strokeWidth="1.8" />
          <path d="M398,182 L442,182 M398,214 L442,214" stroke={O} strokeWidth="1.6" />
          <rect x="18" y="200" width="30" height="50" rx="4" fill="#c0603a" stroke={O} strokeWidth="1.6" />
          <ellipse cx="33" cy="190" rx="22" ry="20" fill="#4fa86a" stroke={O} strokeWidth="1.6" />
        </g>
      );
    case "lab":
      return (
        <g>
          <Window x={330} y={50} w={110} h={90} />
          <rect x="30" y="70" width="170" height="8" fill="#9a6332" />
          {[50, 90, 130, 170].map((x, i) => (
            <rect key={x} x={x} y="44" width="16" height="26" rx="3" fill={["#e63946", "#2a9d8f", "#ffd23f", "#8e44ad"][i]} stroke={O} strokeWidth="1.2" />
          ))}
          <rect x="250" y="196" width="210" height="16" fill="#e8e8e8" stroke={O} strokeWidth="1.6" />
          <path d="M290,196 L290,174 L282,160 L306,160 L298,174 L298,196 Z" fill="#9fe0d4" stroke={O} strokeWidth="1.4" />
          <path d="M340,196 L346,168 L360,168 L366,196 Z" fill="#ffd36b" stroke={O} strokeWidth="1.4" />
        </g>
      );
    default:
      return null;
  }
}

/** Redrawn only when the place or its picture changes. */
export const Backdrop = memo(BackdropView);
