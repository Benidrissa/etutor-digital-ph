/**
 * The cast member drawn while their generated art does not exist yet: a flat
 * cartoon figure in the Scratch prototype's style (thick dark outline, big
 * head, big eyes, soft gradients), built from the actor's look so every cast
 * member is told apart, and posed by mood.
 *
 * Two families: people (a child or an adult, in the same 130 x 240 box, so
 * the stage sizes them) and Margo, the AI tutor, a friendly gecko.
 */

import { memo, useId, type CSSProperties, type ReactNode } from "react";

import type { Look, Pose, StageActor } from "./cast";
import styles from "./stage.module.css";

const OUTLINE = "#3b2418";

interface FigureProps {
  actor: StageActor;
  pose: Pose;
  /** Mouth flaps while a line is being said. */
  talkBeats?: number;
  className?: string;
}

function PlaceholderFigureView({ actor, pose, talkBeats = 0, className }: FigureProps) {
  const rawId = useId();
  const uid = rawId.replace(/[^a-zA-Z0-9_-]/g, "");
  const style = { "--talk-count": talkBeats } as CSSProperties;
  if (actor.figure === "gecko") {
    return (
      <Gecko uid={uid} pose={pose} style={style} className={className} tan={!actor.isTutor} />
    );
  }
  return (
    <Person
      uid={uid}
      look={actor.look}
      adult={actor.figure === "adult"}
      pose={pose}
      style={style}
      className={className}
    />
  );
}

/* -------------------------------------------------------------------------- */
/* People                                                                     */
/* -------------------------------------------------------------------------- */

interface Body {
  headCy: number;
  headR: number;
  shoulderY: number;
  shoulderW: number;
  waistY: number;
  hemSkirt: number;
  hemDress: number;
  hemShorts: number;
  ankleY: number;
  arm: number;
}

const CHILD: Body = {
  headCy: 60,
  headR: 31,
  shoulderY: 100,
  shoulderW: 20,
  waistY: 150,
  hemSkirt: 176,
  hemDress: 182,
  hemShorts: 170,
  ankleY: 214,
  arm: 1,
};

const ADULT: Body = {
  headCy: 44,
  headR: 25,
  shoulderY: 80,
  shoulderW: 24,
  waistY: 146,
  hemSkirt: 190,
  hemDress: 198,
  hemShorts: 174,
  ankleY: 214,
  arm: 1.2,
};

type Point = [number, number];

/** Elbow and hand of one arm for a pose; `side` is -1 (left) or 1 (right). */
function armFor(pose: Pose, side: -1 | 1, body: Body): [Point, Point] {
  const sx = 65 + side * body.shoulderW;
  const sy = body.shoulderY + 4;
  const k = body.arm;
  const out = side;
  switch (pose) {
    case "happy":
      return [
        [sx + out * 12 * k, sy - 12 * k],
        [sx + out * 15 * k, sy - 34 * k],
      ];
    case "surprised":
      return [
        [sx + out * 16 * k, sy + 6 * k],
        [sx + out * 30 * k, sy - 4 * k],
      ];
    case "talk":
      return side === 1
        ? [
            [sx + 14 * k, sy + 20 * k],
            [sx + 22 * k, sy - 2 * k],
          ]
        : [
            [sx - 4 * k, sy + 25 * k],
            [sx - 6 * k, sy + 48 * k],
          ];
    case "think":
      return side === 1
        ? [
            [sx + 6 * k, sy + 26 * k],
            [65 + body.headR * 0.32, body.headCy + body.headR * 0.95],
          ]
        : [
            [sx - 2 * k, sy + 24 * k],
            [65 - 2, sy + 34 * k],
          ];
    case "sad":
      return [
        [sx + out * 1 * k, sy + 26 * k],
        [sx - out * 5 * k, sy + 48 * k],
      ];
    case "walk":
      return side === 1
        ? [
            [sx + 8 * k, sy + 24 * k],
            [sx + 15 * k, sy + 44 * k],
          ]
        : [
            [sx - 6 * k, sy + 25 * k],
            [sx - 1 * k, sy + 48 * k],
          ];
    default:
      return [
        [sx + out * 4 * k, sy + 26 * k],
        [sx + out * 5 * k, sy + 50 * k],
      ];
  }
}

function path(points: Point[]): string {
  return points.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
}

function Stroke({ d, color, width }: { d: string; color: string; width: number }) {
  return (
    <>
      <path d={d} stroke={OUTLINE} strokeWidth={width + 3.5} fill="none" strokeLinecap="round" strokeLinejoin="round" />
      <path d={d} stroke={color} strokeWidth={width} fill="none" strokeLinecap="round" strokeLinejoin="round" />
    </>
  );
}

interface PersonProps {
  uid: string;
  look: Look;
  adult: boolean;
  pose: Pose;
  style: CSSProperties;
  className?: string;
}

function Person({ uid, look, adult, pose, style, className }: PersonProps) {
  const b = adult ? ADULT : CHILD;
  const R = b.headR;
  const cy = b.headCy;
  const skin = `url(#skin-${uid})`;
  const hairColor = look.elder ? "#d8d4cf" : look.hair;
  const has = (accessory: string) => look.accessories.includes(accessory as never);
  const trousers = look.bottomStyle === "trousers";
  const coat = has("coat");

  // Legs: apart when walking, together otherwise.
  const legTop = b.waistY + 2;
  const legs: Array<[Point, Point]> =
    pose === "walk"
      ? [
          [[58, legTop], [52, b.ankleY]],
          [[72, legTop], [78, b.ankleY]],
        ]
      : [
          [[58, legTop], [57, b.ankleY]],
          [[72, legTop], [73, b.ankleY]],
        ];

  const arms = ([-1, 1] as const).map((side) => {
    const [elbow, hand] = armFor(pose, side, b);
    const shoulder: Point = [65 + side * b.shoulderW, b.shoulderY + 4];
    return { side, shoulder, elbow, hand };
  });

  // Hands in front of the body for the think pose; others go behind the head.
  const torsoTop = b.shoulderY;
  const W = b.shoulderW;
  const dress = look.bottomStyle === "dress";
  const torso = dress
    ? `M${65 - W},${torsoTop} Q65,${torsoTop - 6} ${65 + W},${torsoTop} L${65 + W + 3},${b.waistY - 6} L${65 + W + 16},${b.hemDress} Q65,${b.hemDress + 5} ${65 - W - 16},${b.hemDress} L${65 - W - 3},${b.waistY - 6} Z`
    : `M${65 - W},${torsoTop} Q65,${torsoTop - 6} ${65 + W},${torsoTop} L${65 + W + 2},${b.waistY + 2} L${65 - W - 2},${b.waistY + 2} Z`;

  return (
    <svg
      viewBox="0 0 130 240"
      className={className}
      style={{ ...style, height: "100%", aspectRatio: "130 / 240", overflow: "visible" }}
      aria-hidden="true"
      focusable="false"
    >
      <defs>
        <radialGradient id={`skin-${uid}`} cx="0.38" cy="0.32" r="0.8">
          <stop offset="0" stopColor={lighten(look.skin, 0.18)} />
          <stop offset="1" stopColor={look.skin} />
        </radialGradient>
        <linearGradient id={`top-${uid}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={lighten(look.top, 0.12)} />
          <stop offset="1" stopColor={darken(look.top, 0.12)} />
        </linearGradient>
        <linearGradient id={`bottom-${uid}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={lighten(look.bottom, 0.1)} />
          <stop offset="1" stopColor={darken(look.bottom, 0.15)} />
        </linearGradient>
      </defs>

      <ellipse cx="65" cy="229" rx="30" ry="5.5" fill="#000" opacity="0.18" />

      {/* Back hair: puffs and braids sit behind the head and shoulders. */}
      {look.hairStyle === "puffs" ? (
        <>
          <circle cx={65 - R * 0.88} cy={cy - R * 0.62} r={R * 0.56} fill={hairColor} stroke={OUTLINE} strokeWidth="2" />
          <circle cx={65 + R * 0.88} cy={cy - R * 0.62} r={R * 0.56} fill={hairColor} stroke={OUTLINE} strokeWidth="2" />
        </>
      ) : null}
      {look.hairStyle === "braids" ? (
        <g>
          {[-1, 1].map((side) =>
            [0, 1].map((n) => {
              const x = 65 + side * (R * 0.78 + n * 6);
              return (
                <g key={`${side}-${n}`}>
                  <path
                    d={`M${x},${cy - R * 0.3} L${x + side * 2},${cy + R * 1.35}`}
                    stroke={OUTLINE}
                    strokeWidth="8"
                    strokeLinecap="round"
                  />
                  <path
                    d={`M${x},${cy - R * 0.3} L${x + side * 2},${cy + R * 1.35}`}
                    stroke={hairColor}
                    strokeWidth="5"
                    strokeLinecap="round"
                  />
                  <circle cx={x + side * 2} cy={cy + R * 1.42} r="3" fill={look.accent} stroke={OUTLINE} strokeWidth="1.2" />
                </g>
              );
            }),
          )}
        </g>
      ) : null}
      {look.hairStyle === "bun" ? (
        <circle cx="65" cy={cy - R * 1.05} r={R * 0.38} fill={hairColor} stroke={OUTLINE} strokeWidth="2" />
      ) : null}

      {/* Legs and shoes. */}
      {legs.map(([top, bottom], i) => {
        const d = path([top, bottom]);
        return (
          <g key={`leg-${i}`}>
            <Stroke d={d} color={trousers ? look.bottom : look.skin} width={11} />
            {!adult && !trousers && look.bottomStyle !== "shorts" ? (
              <path
                d={path([[bottom[0] + (top[0] - bottom[0]) * 0.28, b.ankleY - 18], bottom])}
                stroke="#ffffff"
                strokeWidth="10"
                strokeLinecap="round"
              />
            ) : null}
            <ellipse
              cx={bottom[0] + (i === 0 ? -2 : 2)}
              cy={b.ankleY + 7}
              rx="10"
              ry="5.6"
              fill="#1b1b1b"
              stroke={OUTLINE}
              strokeWidth="1.8"
            />
            <ellipse cx={bottom[0] + (i === 0 ? 0 : 4)} cy={b.ankleY + 5.5} rx="3" ry="1.4" fill="#fff" opacity="0.35" />
          </g>
        );
      })}

      {/* Lower garment. */}
      {look.bottomStyle === "skirt" ? (
        <g>
          <path
            d={`M${65 - W - 1},${b.waistY - 4} L${65 + W + 1},${b.waistY - 4} L${65 + W + 11},${b.hemSkirt} L${65 - W - 11},${b.hemSkirt} Z`}
            fill={`url(#bottom-${uid})`}
            stroke={OUTLINE}
            strokeWidth="2"
            strokeLinejoin="round"
          />
          {[-2, -1, 0, 1, 2].map((n) => (
            <path
              key={n}
              d={`M${65 + n * 7},${b.waistY} L${65 + n * 9.5},${b.hemSkirt - 2}`}
              stroke={darken(look.bottom, 0.3)}
              strokeWidth="1.2"
            />
          ))}
        </g>
      ) : null}
      {look.bottomStyle === "shorts" ? (
        <path
          d={`M${65 - W - 1},${b.waistY - 4} L${65 + W + 1},${b.waistY - 4} L${65 + W + 4},${b.hemShorts} L${67},${b.hemShorts} L65,${b.waistY + 8} L63,${b.hemShorts} L${65 - W - 4},${b.hemShorts} Z`}
          fill={`url(#bottom-${uid})`}
          stroke={OUTLINE}
          strokeWidth="2"
          strokeLinejoin="round"
        />
      ) : null}
      {trousers ? (
        <rect x={65 - W - 2} y={b.waistY - 6} width={W * 2 + 4} height="9" rx="2" fill={darken(look.bottom, 0.1)} stroke={OUTLINE} strokeWidth="1.6" />
      ) : null}

      {/* Arms behind the body for the poses that keep them at the sides. */}
      {arms.map(({ side, shoulder, elbow, hand }) =>
        pose === "think" && side === 1 ? null : (
          <Arm key={side} shoulder={shoulder} elbow={elbow} hand={hand} sleeve={coat ? "#f4f4f0" : look.top} skin={look.skin} />
        ),
      )}

      {/* Torso. */}
      <path d={torso} fill={`url(#top-${uid})`} stroke={OUTLINE} strokeWidth="2" strokeLinejoin="round" />
      {dress ? (
        <g opacity="0.85">
          {[0, 1, 2, 3].map((n) => (
            <circle key={n} cx={65 - 18 + n * 12} cy={b.hemDress - 10} r="3.2" fill={look.accent} stroke={OUTLINE} strokeWidth="0.8" />
          ))}
          {[0, 1, 2].map((n) => (
            <circle key={`b${n}`} cx={65 - 12 + n * 12} cy={b.waistY + 8} r="2.6" fill={look.accent} stroke={OUTLINE} strokeWidth="0.8" />
          ))}
        </g>
      ) : null}
      {coat ? (
        <g>
          <path
            d={`M${65 - W - 3},${torsoTop + 1} L${65 - 7},${torsoTop + 6} L${65 - 6},${b.waistY + 22} L${65 - W - 5},${b.waistY + 22} Z`}
            fill="#f7f7f2"
            stroke={OUTLINE}
            strokeWidth="1.8"
            strokeLinejoin="round"
          />
          <path
            d={`M${65 + W + 3},${torsoTop + 1} L${65 + 7},${torsoTop + 6} L${65 + 6},${b.waistY + 22} L${65 + W + 5},${b.waistY + 22} Z`}
            fill="#f7f7f2"
            stroke={OUTLINE}
            strokeWidth="1.8"
            strokeLinejoin="round"
          />
        </g>
      ) : null}
      {/* Collar, and the tie or the school badge. */}
      <path
        d={`M${65 - 9},${torsoTop - 2} L65,${torsoTop + 8} L${65 + 9},${torsoTop - 2}`}
        stroke={OUTLINE}
        strokeWidth="1.8"
        fill={look.top.toLowerCase() === "#ffffff" ? "#2b4ea2" : "#ffffff"}
        strokeLinejoin="round"
      />
      {has("tie") ? (
        <path
          d={`M62,${torsoTop + 8} L68,${torsoTop + 8} L70,${torsoTop + 40} L65,${torsoTop + 47} L60,${torsoTop + 40} Z`}
          fill={look.accent === "#ffd23f" ? "#c1272d" : look.accent}
          stroke={OUTLINE}
          strokeWidth="1.5"
        />
      ) : !adult ? (
        <circle cx={65 + W * 0.45} cy={torsoTop + 16} r="3.4" fill="#f1c40f" stroke={OUTLINE} strokeWidth="1.2" />
      ) : null}

      {/* Neck and head. */}
      <rect x="59" y={cy + R * 0.85} width="12" height={torsoTop - (cy + R * 0.85) + 2} fill={look.skin} stroke={OUTLINE} strokeWidth="1.6" />
      <circle cx={65 - R} cy={cy + 3} r={R * 0.2} fill={skin} stroke={OUTLINE} strokeWidth="1.8" />
      <circle cx={65 + R} cy={cy + 3} r={R * 0.2} fill={skin} stroke={OUTLINE} strokeWidth="1.8" />
      <ellipse cx="65" cy={cy} rx={R} ry={R * 1.02} fill={skin} stroke={OUTLINE} strokeWidth="2.2" />

      {has("beard") ? (
        <path
          d={`M${65 - R * 0.86},${cy + R * 0.15} Q${65 - R * 0.8},${cy + R * 1.08} 65,${cy + R * 1.1} Q${65 + R * 0.8},${cy + R * 1.08} ${65 + R * 0.86},${cy + R * 0.15} Q${65 + R * 0.55},${cy + R * 0.62} 65,${cy + R * 0.6} Q${65 - R * 0.55},${cy + R * 0.62} ${65 - R * 0.86},${cy + R * 0.15} Z`}
          fill={hairColor}
          stroke={OUTLINE}
          strokeWidth="1.6"
        />
      ) : null}

      <Hair look={look} hairColor={hairColor} R={R} cy={cy} />
      <Face pose={pose} R={R} cy={cy} skin={look.skin} glasses={has("glasses")} beard={has("beard")} />

      {/* The thinking hand in front of the face. */}
      {pose === "think"
        ? arms
            .filter(({ side }) => side === 1)
            .map(({ shoulder, elbow, hand }) => (
              <Arm key="chin" shoulder={shoulder} elbow={elbow} hand={hand} sleeve={coat ? "#f4f4f0" : look.top} skin={look.skin} />
            ))
        : null}

      {/* Things in hand. */}
      {has("pointer") && (pose === "idle" || pose === "talk") ? (
        <g>
          <path
            d={`M${arms[1].hand[0] - 2},${arms[1].hand[1] + 4} L${arms[1].hand[0] + 24},${arms[1].hand[1] - 34}`}
            stroke="#8a5a2b"
            strokeWidth="3"
            strokeLinecap="round"
          />
          <circle cx={arms[1].hand[0] + 24} cy={arms[1].hand[1] - 34} r="2.6" fill="#c1272d" />
          <circle cx={arms[1].hand[0]} cy={arms[1].hand[1]} r="5.6" fill={look.skin} stroke={OUTLINE} strokeWidth="1.8" />
        </g>
      ) : null}
      {has("basket") && pose !== "happy" && pose !== "surprised" ? (
        <g>
          <path
            d={`M${arms[0].hand[0] - 10},${arms[0].hand[1] + 2} Q${arms[0].hand[0]},${arms[0].hand[1] - 14} ${arms[0].hand[0] + 10},${arms[0].hand[1] + 2}`}
            stroke="#8a5a2b"
            strokeWidth="2.4"
            fill="none"
          />
          <path
            d={`M${arms[0].hand[0] - 13},${arms[0].hand[1] + 2} L${arms[0].hand[0] + 13},${arms[0].hand[1] + 2} L${arms[0].hand[0] + 9},${arms[0].hand[1] + 16} L${arms[0].hand[0] - 9},${arms[0].hand[1] + 16} Z`}
            fill="#d9a441"
            stroke={OUTLINE}
            strokeWidth="1.6"
          />
          <circle cx={arms[0].hand[0] - 4} cy={arms[0].hand[1]} r="4" fill="#ff9f1c" stroke={OUTLINE} strokeWidth="1" />
          <circle cx={arms[0].hand[0] + 4} cy={arms[0].hand[1] - 1} r="4" fill="#f4d35e" stroke={OUTLINE} strokeWidth="1" />
        </g>
      ) : null}
    </svg>
  );
}

function Arm({
  shoulder,
  elbow,
  hand,
  sleeve,
  skin,
}: {
  shoulder: Point;
  elbow: Point;
  hand: Point;
  sleeve: string;
  skin: string;
}) {
  const sleeveEnd: Point = [
    shoulder[0] + (elbow[0] - shoulder[0]) * 0.7,
    shoulder[1] + (elbow[1] - shoulder[1]) * 0.7,
  ];
  return (
    <g>
      <Stroke d={path([shoulder, elbow, hand])} color={skin} width={8.5} />
      <Stroke d={path([shoulder, sleeveEnd])} color={sleeve} width={11} />
      <circle cx={hand[0]} cy={hand[1]} r="5.6" fill={skin} stroke={OUTLINE} strokeWidth="1.8" />
    </g>
  );
}

function Hair({ look, hairColor, R, cy }: { look: Look; hairColor: string; R: number; cy: number }) {
  const has = (accessory: string) => look.accessories.includes(accessory as never);
  if (look.hairStyle === "wrap") {
    return (
      <g>
        <path
          d={`M${65 - R * 1.05},${cy - R * 0.2} Q${65 - R * 1.25},${cy - R * 1.6} 65,${cy - R * 1.55} Q${65 + R * 1.3},${cy - R * 1.6} ${65 + R * 1.05},${cy - R * 0.2} Q65,${cy - R * 0.62} ${65 - R * 1.05},${cy - R * 0.2} Z`}
          fill={look.accent}
          stroke={OUTLINE}
          strokeWidth="2"
          strokeLinejoin="round"
        />
        <circle cx={65 + R * 0.35} cy={cy - R * 1.45} r={R * 0.3} fill={look.accent} stroke={OUTLINE} strokeWidth="1.8" />
        {[-0.6, -0.2, 0.2, 0.6].map((dx) => (
          <circle key={dx} cx={65 + R * dx} cy={cy - R * 0.95} r="1.8" fill="#ffd23f" />
        ))}
      </g>
    );
  }
  if (look.hairStyle === "bald") {
    return (
      <g>
        <path d={`M${65 - R * 0.98},${cy - R * 0.1} Q${65 - R},${cy - R * 0.5} ${65 - R * 0.8},${cy - R * 0.6}`} stroke={hairColor} strokeWidth="5" strokeLinecap="round" fill="none" />
        <path d={`M${65 + R * 0.98},${cy - R * 0.1} Q${65 + R},${cy - R * 0.5} ${65 + R * 0.8},${cy - R * 0.6}`} stroke={hairColor} strokeWidth="5" strokeLinecap="round" fill="none" />
        <ellipse cx={65 - R * 0.35} cy={cy - R * 0.72} rx={R * 0.2} ry={R * 0.09} fill="#fff" opacity="0.35" />
      </g>
    );
  }
  const short = look.hairStyle === "short";
  const cap = short
    ? `M${65 - R * 1.0},${cy - R * 0.08} Q${65 - R * 1.08},${cy - R * 1.12} 65,${cy - R * 1.12} Q${65 + R * 1.08},${cy - R * 1.12} ${65 + R * 1.0},${cy - R * 0.08} Q${65 + R * 0.86},${cy - R * 0.62} ${65 + R * 0.3},${cy - R * 0.66} Q65,${cy - R * 0.5} ${65 - R * 0.35},${cy - R * 0.66} Q${65 - R * 0.86},${cy - R * 0.62} ${65 - R * 1.0},${cy - R * 0.08} Z`
    : `M${65 - R * 1.04},${cy + R * 0.12} Q${65 - R * 1.14},${cy - R * 1.2} 65,${cy - R * 1.16} Q${65 + R * 1.14},${cy - R * 1.2} ${65 + R * 1.04},${cy + R * 0.12} Q${65 + R * 0.92},${cy - R * 0.52} ${65 + R * 0.25},${cy - R * 0.58} Q65,${cy - R * 0.42} ${65 - R * 0.25},${cy - R * 0.58} Q${65 - R * 0.92},${cy - R * 0.52} ${65 - R * 1.04},${cy + R * 0.12} Z`;
  return (
    <g>
      <path d={cap} fill={hairColor} stroke={OUTLINE} strokeWidth="2" strokeLinejoin="round" />
      <path
        d={`M${65 - R * 0.5},${cy - R * 0.95} Q65,${cy - R * 1.05} ${65 + R * 0.4},${cy - R * 0.92}`}
        stroke="#ffffff"
        strokeOpacity="0.18"
        strokeWidth="3"
        fill="none"
        strokeLinecap="round"
      />
      {has("headband") ? (
        <>
          <path
            d={`M${65 - R * 0.98},${cy - R * 0.42} Q65,${cy - R * 1.35} ${65 + R * 0.98},${cy - R * 0.42}`}
            stroke={OUTLINE}
            strokeWidth="6.5"
            fill="none"
            strokeLinecap="round"
          />
          <path
            d={`M${65 - R * 0.98},${cy - R * 0.42} Q65,${cy - R * 1.35} ${65 + R * 0.98},${cy - R * 0.42}`}
            stroke={look.accent}
            strokeWidth="4"
            fill="none"
            strokeLinecap="round"
          />
          {look.feminine ? (
            <circle cx={65 + R * 0.72} cy={cy - R * 0.9} r={R * 0.16} fill={look.accent} stroke={OUTLINE} strokeWidth="1.5" />
          ) : null}
        </>
      ) : null}
    </g>
  );
}

function Face({
  pose,
  R,
  cy,
  skin,
  glasses,
  beard,
}: {
  pose: Pose;
  R: number;
  cy: number;
  skin: string;
  glasses: boolean;
  beard: boolean;
}) {
  const ey = cy + R * 0.02;
  const ex = R * 0.36;
  const eyeRx = R * 0.2;
  const eyeRy = pose === "surprised" ? R * 0.28 : R * 0.24;
  const my = cy + R * 0.52;
  const look: Point =
    pose === "think" ? [-R * 0.06, -R * 0.09] : pose === "sad" ? [0, R * 0.07] : [0, R * 0.02];
  const irisR = pose === "surprised" ? R * 0.1 : R * 0.13;

  const brows: Record<string, (side: number) => string> = {
    sad: (side) =>
      `M${65 + side * ex - side * R * 0.18},${ey - R * 0.38} Q${65 + side * ex},${ey - R * 0.33} ${65 + side * ex + side * R * 0.2},${ey - R * 0.27}`,
    surprised: (side) =>
      `M${65 + side * ex - R * 0.18},${ey - R * 0.42} Q${65 + side * ex},${ey - R * 0.56} ${65 + side * ex + R * 0.18},${ey - R * 0.42}`,
    think: (side) =>
      side === -1
        ? `M${65 - ex - R * 0.18},${ey - R * 0.44} Q${65 - ex},${ey - R * 0.56} ${65 - ex + R * 0.18},${ey - R * 0.46}`
        : `M${65 + ex - R * 0.18},${ey - R * 0.34} L${65 + ex + R * 0.18},${ey - R * 0.34}`,
  };
  const brow =
    brows[pose] ??
    ((side: number) =>
      `M${65 + side * ex - R * 0.17},${ey - R * 0.36} Q${65 + side * ex},${ey - R * 0.44} ${65 + side * ex + R * 0.17},${ey - R * 0.36}`);

  return (
    <g>
      {/* Eyes. Happy eyes are closed arcs; the rest blink. */}
      {[-1, 1].map((side) => {
        const x = 65 + side * ex;
        if (pose === "happy") {
          return (
            <path
              key={side}
              d={`M${x - eyeRx},${ey + 2} Q${x},${ey - eyeRy * 1.2} ${x + eyeRx},${ey + 2}`}
              stroke={OUTLINE}
              strokeWidth="2.6"
              fill="none"
              strokeLinecap="round"
            />
          );
        }
        return (
          <g key={side}>
            <ellipse cx={x} cy={ey} rx={eyeRx} ry={eyeRy} fill="#fff" stroke={OUTLINE} strokeWidth="1.8" />
            <circle cx={x + look[0]} cy={ey + look[1]} r={irisR} fill="#3a2214" />
            <circle cx={x + look[0]} cy={ey + look[1]} r={irisR * 0.5} fill="#120a06" />
            <circle cx={x + look[0] + irisR * 0.35} cy={ey + look[1] - irisR * 0.4} r={irisR * 0.32} fill="#fff" />
            <ellipse
              className={styles.lid}
              cx={x}
              cy={ey}
              rx={eyeRx + 0.8}
              ry={eyeRy + 0.8}
              fill={skin}
              stroke={OUTLINE}
              strokeWidth="1.2"
            />
          </g>
        );
      })}
      {[-1, 1].map((side) => (
        <path key={`brow${side}`} d={brow(side)} stroke={OUTLINE} strokeWidth="2.2" fill="none" strokeLinecap="round" />
      ))}

      {glasses ? (
        <g fill="#ffffff" fillOpacity="0.12" stroke="#1f1f1f" strokeWidth="2">
          <circle cx={65 - ex} cy={ey} r={R * 0.29} />
          <circle cx={65 + ex} cy={ey} r={R * 0.29} />
          <path d={`M${65 - ex + R * 0.29},${ey} Q65,${ey - R * 0.08} ${65 + ex - R * 0.29},${ey}`} fill="none" />
        </g>
      ) : null}

      {/* Nose and cheeks. */}
      <path
        d={`M${65 - R * 0.07},${cy + R * 0.3} Q65,${cy + R * 0.38} ${65 + R * 0.07},${cy + R * 0.3}`}
        stroke={OUTLINE}
        strokeWidth="1.6"
        fill="none"
        strokeLinecap="round"
      />
      {!beard ? (
        <>
          <circle cx={65 - R * 0.6} cy={cy + R * 0.36} r={R * 0.13} fill="#ff6b6b" opacity="0.32" />
          <circle cx={65 + R * 0.6} cy={cy + R * 0.36} r={R * 0.13} fill="#ff6b6b" opacity="0.32" />
        </>
      ) : null}

      <Mouth pose={pose} R={R} my={my} />
    </g>
  );
}

function Mouth({ pose, R, my }: { pose: Pose; R: number; my: number }) {
  const open = (
    <g className={styles.mouthOpen}>
      <ellipse cx="65" cy={my + R * 0.04} rx={R * 0.18} ry={R * 0.14} fill="#6b1f1f" stroke={OUTLINE} strokeWidth="1.6" />
      <ellipse cx="65" cy={my + R * 0.11} rx={R * 0.1} ry={R * 0.05} fill="#ff8a8a" />
    </g>
  );
  let shape: ReactNode;
  switch (pose) {
    case "happy":
      shape = (
        <g>
          <path
            d={`M${65 - R * 0.32},${my - 3} Q65,${my + R * 0.5} ${65 + R * 0.32},${my - 3} Z`}
            fill="#6b1f1f"
            stroke={OUTLINE}
            strokeWidth="1.8"
            strokeLinejoin="round"
          />
          <path d={`M${65 - R * 0.26},${my - 1} L${65 + R * 0.26},${my - 1}`} stroke="#fff" strokeWidth="3" />
          <ellipse cx="65" cy={my + R * 0.24} rx={R * 0.12} ry={R * 0.06} fill="#ff8a8a" />
        </g>
      );
      break;
    case "think":
      shape = (
        <path
          d={`M${65 - R * 0.08},${my + 2} Q${65 + R * 0.04},${my - 1} ${65 + R * 0.18},${my + 1}`}
          stroke={OUTLINE}
          strokeWidth="2.2"
          fill="none"
          strokeLinecap="round"
        />
      );
      break;
    case "sad":
      shape = (
        <path
          d={`M${65 - R * 0.2},${my + R * 0.12} Q65,${my - R * 0.06} ${65 + R * 0.2},${my + R * 0.12}`}
          stroke={OUTLINE}
          strokeWidth="2.2"
          fill="none"
          strokeLinecap="round"
        />
      );
      break;
    case "surprised":
      shape = <ellipse cx="65" cy={my + 2} rx={R * 0.1} ry={R * 0.14} fill="#6b1f1f" stroke={OUTLINE} strokeWidth="1.6" />;
      break;
    default:
      shape = (
        <path
          d={`M${65 - R * 0.22},${my} Q65,${my + R * 0.22} ${65 + R * 0.22},${my}`}
          stroke={OUTLINE}
          strokeWidth="2.2"
          fill="none"
          strokeLinecap="round"
        />
      );
  }
  return (
    <g>
      {shape}
      {pose === "talk" || pose === "idle" ? open : null}
    </g>
  );
}

/* -------------------------------------------------------------------------- */
/* Margo the gecko                                                            */
/* -------------------------------------------------------------------------- */

function geckoArm(pose: Pose, side: -1 | 1): [Point, Point] {
  const sx = 60 + side * 17;
  const sy = 84;
  switch (pose) {
    case "happy":
      return [
        [sx + side * 9, sy - 8],
        [sx + side * 12, sy - 24],
      ];
    case "surprised":
      return [
        [sx + side * 12, sy + 2],
        [sx + side * 22, sy - 6],
      ];
    case "talk":
      return side === 1
        ? [
            [sx + 10, sy + 6],
            [sx + 16, sy - 10],
          ]
        : [
            [sx - 6, sy + 10],
            [sx - 8, sy + 20],
          ];
    case "think":
      return side === 1
        ? [
            [sx + 4, sy + 10],
            [70, 70],
          ]
        : [
            [sx - 6, sy + 10],
            [sx - 8, sy + 20],
          ];
    default:
      return [
        [sx + side * 6, sy + 10],
        [sx + side * 8, sy + 21],
      ];
  }
}

function Gecko({
  uid,
  pose,
  style,
  className,
  tan,
}: {
  uid: string;
  pose: Pose;
  style: CSSProperties;
  className?: string;
  /** A plain animal, not the tutor: sand-coloured instead of green. */
  tan: boolean;
}) {
  const body = tan ? "#d9a35b" : "#5cbf4a";
  const dark = tan ? "#b07b3a" : "#3e9a35";
  const belly = tan ? "#f3dcae" : "#d7f59a";
  const spot = tan ? "#8a5a2b" : "#ff9f1c";
  const happy = pose === "happy";
  const toes = (x: number, y: number, key: string) => (
    <g key={key}>
      {[-5, 0, 5].map((dx) => (
        <circle key={dx} cx={x + dx} cy={y} r="3.4" fill={body} stroke={OUTLINE} strokeWidth="1.4" />
      ))}
    </g>
  );
  const arms = ([-1, 1] as const).map((side) => {
    const [elbow, hand] = geckoArm(pose, side);
    return { side, shoulder: [60 + side * 17, 84] as Point, elbow, hand };
  });

  return (
    <svg
      viewBox="0 0 120 130"
      className={className}
      style={{ ...style, height: "100%", aspectRatio: "120 / 130", overflow: "visible" }}
      aria-hidden="true"
      focusable="false"
    >
      <defs>
        <radialGradient id={`gecko-${uid}`} cx="0.4" cy="0.3" r="0.8">
          <stop offset="0" stopColor={lighten(body, 0.2)} />
          <stop offset="1" stopColor={dark} />
        </radialGradient>
      </defs>
      <ellipse cx="60" cy="126" rx="30" ry="4" fill="#000" opacity="0.18" />
      {/* Curled tail. */}
      <path d="M72,110 C102,116 114,92 102,80 C94,72 84,80 91,88" stroke={OUTLINE} strokeWidth="13" fill="none" strokeLinecap="round" />
      <path d="M72,110 C102,116 114,92 102,80 C94,72 84,80 91,88" stroke={body} strokeWidth="9" fill="none" strokeLinecap="round" />
      {/* Legs and toe pads. */}
      <path d="M48,104 L46,118" stroke={OUTLINE} strokeWidth="12" strokeLinecap="round" />
      <path d="M48,104 L46,118" stroke={body} strokeWidth="8.5" strokeLinecap="round" />
      <path d="M72,104 L74,118" stroke={OUTLINE} strokeWidth="12" strokeLinecap="round" />
      <path d="M72,104 L74,118" stroke={body} strokeWidth="8.5" strokeLinecap="round" />
      {toes(45, 121, "lf")}
      {toes(75, 121, "rf")}
      {/* Body and belly. */}
      <ellipse cx="60" cy="92" rx="22" ry="24" fill={`url(#gecko-${uid})`} stroke={OUTLINE} strokeWidth="2.2" />
      <ellipse cx="60" cy="96" rx="13" ry="16" fill={belly} stroke={OUTLINE} strokeWidth="1.2" />
      <circle cx="43" cy="88" r="3" fill={spot} />
      <circle cx="78" cy="96" r="2.6" fill={spot} />
      {/* Arms. */}
      {arms.map(({ side, shoulder, elbow, hand }) => (
        <g key={side}>
          <path d={path([shoulder, elbow, hand])} stroke={OUTLINE} strokeWidth="10" fill="none" strokeLinecap="round" strokeLinejoin="round" />
          <path d={path([shoulder, elbow, hand])} stroke={body} strokeWidth="6.5" fill="none" strokeLinecap="round" strokeLinejoin="round" />
          {toes(hand[0], hand[1], `h${side}`)}
        </g>
      ))}
      {/* Bow tie: Margo dresses up for class. */}
      {!tan ? (
        <g>
          <path d="M60,72 L49,66 L49,78 Z" fill="#2ec4b6" stroke={OUTLINE} strokeWidth="1.6" strokeLinejoin="round" />
          <path d="M60,72 L71,66 L71,78 Z" fill="#2ec4b6" stroke={OUTLINE} strokeWidth="1.6" strokeLinejoin="round" />
          <circle cx="60" cy="72" r="3.2" fill="#1a9a8f" stroke={OUTLINE} strokeWidth="1.4" />
        </g>
      ) : null}
      {/* Head. */}
      <ellipse cx="60" cy="48" rx="34" ry="25" fill={`url(#gecko-${uid})`} stroke={OUTLINE} strokeWidth="2.2" />
      <circle cx="48" cy="30" r="2.6" fill={spot} />
      <circle cx="74" cy="27" r="2.2" fill={spot} />
      <circle cx="62" cy="24" r="1.8" fill={spot} />
      {/* Big round eyes on top. */}
      {[-1, 1].map((side) => {
        const x = 60 + side * 19;
        if (happy) {
          return (
            <g key={side}>
              <circle cx={x} cy="36" r="12" fill={body} stroke={OUTLINE} strokeWidth="2" />
              <path d={`M${x - 7},38 Q${x},28 ${x + 7},38`} stroke={OUTLINE} strokeWidth="2.8" fill="none" strokeLinecap="round" />
            </g>
          );
        }
        const lookX = pose === "think" ? -2.5 : 0;
        const lookY = pose === "think" ? -3 : 1;
        return (
          <g key={side}>
            <circle cx={x} cy="36" r="12" fill="#fff" stroke={OUTLINE} strokeWidth="2" />
            <circle cx={x + lookX} cy={36 + lookY} r="7.2" fill="#1d1d1b" />
            <circle cx={x + lookX + 2.4} cy={33 + lookY} r="2.6" fill="#fff" />
            <ellipse className={styles.lid} cx={x} cy="36" rx="12.8" ry="12.8" fill={body} stroke={OUTLINE} strokeWidth="1.2" />
          </g>
        );
      })}
      {/* Nostrils, cheeks and mouth. */}
      <circle cx="56" cy="50" r="1.2" fill={OUTLINE} />
      <circle cx="64" cy="50" r="1.2" fill={OUTLINE} />
      <circle cx="34" cy="55" r="4" fill="#ff6b6b" opacity="0.35" />
      <circle cx="86" cy="55" r="4" fill="#ff6b6b" opacity="0.35" />
      {happy ? (
        <path d="M42,56 Q60,76 78,56 Z" fill="#6b1f1f" stroke={OUTLINE} strokeWidth="2" strokeLinejoin="round" />
      ) : pose === "sad" ? (
        <path d="M46,64 Q60,54 74,64" stroke={OUTLINE} strokeWidth="2.4" fill="none" strokeLinecap="round" />
      ) : pose === "surprised" ? (
        <ellipse cx="60" cy="61" rx="5" ry="6" fill="#6b1f1f" stroke={OUTLINE} strokeWidth="1.6" />
      ) : (
        <g>
          <path d="M40,56 Q60,70 80,56" stroke={OUTLINE} strokeWidth="2.4" fill="none" strokeLinecap="round" />
          {pose === "talk" || pose === "idle" ? (
            <g className={styles.mouthOpen}>
              <path d="M46,58 Q60,74 74,58 Z" fill="#6b1f1f" stroke={OUTLINE} strokeWidth="1.8" />
              <ellipse cx="60" cy="65" rx="6" ry="2.6" fill="#ff8a8a" />
            </g>
          ) : null}
        </g>
      )}
    </svg>
  );
}

/* -------------------------------------------------------------------------- */
/* Colour helpers                                                             */
/* -------------------------------------------------------------------------- */

function channels(hex: string): [number, number, number] {
  const value = hex.replace("#", "");
  const full = value.length === 3 ? value.split("").map((c) => c + c).join("") : value.padEnd(6, "0");
  return [0, 2, 4].map((i) => parseInt(full.slice(i, i + 2), 16) || 0) as [number, number, number];
}

function toHex([r, g, b]: [number, number, number]): string {
  return `#${[r, g, b].map((c) => Math.round(Math.min(255, Math.max(0, c))).toString(16).padStart(2, "0")).join("")}`;
}

export function lighten(hex: string, amount: number): string {
  return toHex(channels(hex).map((c) => c + (255 - c) * amount) as [number, number, number]);
}

export function darken(hex: string, amount: number): string {
  return toHex(channels(hex).map((c) => c * (1 - amount)) as [number, number, number]);
}

/** Redrawn only when the actor, pose or line changes. */
export const PlaceholderFigure = memo(PlaceholderFigureView);
