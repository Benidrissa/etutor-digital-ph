/**
 * Concept widgets for the story player (format Appendix A.8).
 *
 * Each widget is drawn from the numbers in `params`, never from a bitmap, so
 * the picture cannot disagree with the maths it illustrates — that is the
 * point of the catalog. Widgets are plain SVG with a `viewBox`, so they scale
 * from a 320px phone up without shipping any image bytes.
 *
 * The one exception is `image` (contract X4): a figure taken from the course's
 * own source documents, shown through the lesson's existing SourceImage so a
 * story figure looks, loads and zooms exactly like the same figure in the
 * lesson.
 *
 * A visual this component does not implement yet renders as a short, neutral
 * placeholder. Its name and numbers are internal, so they go to the console
 * for whoever is filling the gap, never on the learner's screen.
 */

"use client";

import { useTranslations } from "next-intl";
import { useEffect, useMemo, type ReactNode } from "react";

import { SourceImage } from "@/components/learning/source-image";
import {
  divisionLadder,
  factorTree,
  indexFormOf,
  isPrime,
  primeFactors,
  treeDepth,
  type TreeNode,
} from "@/lib/story-course/numbers";

interface ConceptVisualProps {
  visual: string;
  params?: Record<string, unknown>;
  /** Localized caption, when the step carries one. */
  caption?: string;
  /** Accessible description; falls back to a generated one. */
  label?: string;
  /**
   * The learner's language. Only `image` needs it: a source figure carries
   * its own alt text per language and is served per language.
   */
  language?: "fr" | "en";
}

const num = (value: unknown, fallback = 0): number => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
};

export function ConceptVisual({
  visual,
  params,
  caption,
  label,
  language = "en",
}: ConceptVisualProps) {
  if (visual === "image") {
    return <SourceFigure params={params} caption={caption} language={language} />;
  }
  return <DrawnVisual visual={visual} params={params} caption={caption} label={label} />;
}

function DrawnVisual({
  visual,
  params,
  caption,
  label,
}: Omit<ConceptVisualProps, "language">) {
  const t = useTranslations("Story");
  const body = useMemo<ReactNode | null>(() => {
    switch (visual) {
      case "hundred_square":
        return <HundredSquare highlight={String(params?.highlight ?? "primes")} />;
      case "factor_tree":
        return (
          <FactorTree
            n={num(params?.n, 12)}
            firstSplit={
              Array.isArray(params?.first_split) && params.first_split.length === 2
                ? [num(params.first_split[0]), num(params.first_split[1])]
                : undefined
            }
          />
        );
      case "division_ladder":
        return <DivisionLadder n={num(params?.n, 12)} />;
      case "venn_primes":
        return <VennPrimes a={num(params?.a, 12)} b={num(params?.b, 18)} />;
      default:
        return null;
    }
  }, [visual, params]);

  useEffect(() => {
    if (body !== null) return;
    // For whoever adds the widget; the learner only sees the placeholder.
    console.warn(`Story player: visual "${visual}" is not drawn yet`, params ?? {});
  }, [body, visual, params]);

  if (body === null) {
    return (
      <figure className="my-4">
        <p className="rounded-lg border border-dashed border-gray-300 bg-gray-50 p-4 text-center text-sm text-gray-500">
          {t("visualUnavailable")}
        </p>
        {caption ? (
          <figcaption className="mt-2 text-center text-sm text-gray-600">{caption}</figcaption>
        ) : null}
      </figure>
    );
  }

  return (
    <figure className="my-4">
      <div
        role="img"
        aria-label={label ?? caption ?? `${visual} diagram`}
        className="w-full overflow-x-auto rounded-lg border border-teal-100 bg-white p-3"
      >
        {body}
      </div>
      {caption ? (
        <figcaption className="mt-2 text-center text-sm text-gray-600">{caption}</figcaption>
      ) : null}
    </figure>
  );
}

/* -------------------------------------------------------------------------- */
/* image (contract X4)                                                        */
/* -------------------------------------------------------------------------- */

const nonEmpty = (value: unknown): string | undefined => {
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
};

/**
 * `{source_image_id, figure_number, alt: {en, fr}}` drawn by the lesson's
 * SourceImage. Without an image id there is nothing to show, so nothing is.
 */
function SourceFigure({
  params,
  caption,
  language,
}: {
  params?: Record<string, unknown>;
  caption?: string;
  language: "fr" | "en";
}) {
  const id = nonEmpty(params?.source_image_id);
  if (!id) return null;
  const alt =
    params?.alt && typeof params.alt === "object"
      ? (params.alt as Record<string, unknown>)
      : {};
  return (
    <SourceImage
      id={id}
      figure_number={nonEmpty(params?.figure_number)}
      alt_text_en={nonEmpty(alt.en)}
      alt_text_fr={nonEmpty(alt.fr)}
      caption={caption}
      language={language}
    />
  );
}

/* -------------------------------------------------------------------------- */
/* hundred_square                                                             */
/* -------------------------------------------------------------------------- */

function HundredSquare({ highlight }: { highlight: string }) {
  const cell = 28;
  const multipleOf = highlight.startsWith("multiples:")
    ? Number(highlight.split(":")[1])
    : null;

  const isMarked = (n: number): boolean => {
    if (multipleOf && multipleOf > 0) return n % multipleOf === 0;
    if (highlight === "primes") return isPrime(n);
    return false;
  };

  return (
    <svg viewBox={`0 0 ${cell * 10} ${cell * 10}`} className="mx-auto block w-full max-w-md">
      {Array.from({ length: 100 }, (_, index) => {
        const value = index + 1;
        const col = index % 10;
        const row = Math.floor(index / 10);
        const marked = isMarked(value);
        return (
          <g key={value}>
            <rect
              x={col * cell}
              y={row * cell}
              width={cell}
              height={cell}
              className={marked ? "fill-teal-500" : "fill-white"}
              stroke="#d1d5db"
              strokeWidth="0.5"
            />
            <text
              x={col * cell + cell / 2}
              y={row * cell + cell / 2 + 4}
              textAnchor="middle"
              fontSize="11"
              className={marked ? "fill-white font-semibold" : "fill-gray-600"}
            >
              {value}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

/* -------------------------------------------------------------------------- */
/* factor_tree                                                                */
/* -------------------------------------------------------------------------- */

function FactorTree({ n, firstSplit }: { n: number; firstSplit?: [number, number] }) {
  const tree = useMemo(() => factorTree(n, firstSplit), [n, firstSplit]);
  const depth = treeDepth(tree);
  const levelHeight = 62;
  const width = Math.max(300, 2 ** Math.min(depth - 1, 4) * 80);
  const height = depth * levelHeight + 20;

  const nodes: { x: number; y: number; value: number; leaf: boolean }[] = [];
  const edges: { x1: number; y1: number; x2: number; y2: number }[] = [];

  const walk = (node: TreeNode, x: number, y: number, span: number) => {
    const leaf = !node.children;
    nodes.push({ x, y, value: node.value, leaf });
    if (!node.children) return;
    const childY = y + levelHeight;
    const offset = span / 2;
    const positions: [number, number] = [x - offset, x + offset];
    node.children.forEach((child, index) => {
      edges.push({ x1: x, y1: y + 14, x2: positions[index], y2: childY - 14 });
      walk(child, positions[index], childY, span / 2);
    });
  };
  walk(tree, width / 2, 28, width / 4);

  return (
    <div>
      <svg viewBox={`0 0 ${width} ${height}`} className="mx-auto block w-full max-w-lg">
        {edges.map((edge, index) => (
          <line
            key={index}
            x1={edge.x1}
            y1={edge.y1}
            x2={edge.x2}
            y2={edge.y2}
            stroke="#99f6e4"
            strokeWidth="2"
          />
        ))}
        {nodes.map((node, index) => (
          <g key={index}>
            <circle
              cx={node.x}
              cy={node.y}
              r="16"
              className={node.leaf ? "fill-amber-400" : "fill-teal-600"}
            />
            <text
              x={node.x}
              y={node.y + 4}
              textAnchor="middle"
              fontSize="12"
              className="fill-white font-semibold"
            >
              {node.value}
            </text>
          </g>
        ))}
      </svg>
      <p className="mt-1 text-center text-sm text-gray-700">
        {n} = {indexFormOf(n)}
      </p>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* division_ladder                                                            */
/* -------------------------------------------------------------------------- */

function DivisionLadder({ n }: { n: number }) {
  const rows = useMemo(() => divisionLadder(n), [n]);

  return (
    <div className="mx-auto w-fit">
      <table className="font-mono text-sm">
        <caption className="sr-only">Division ladder for {n}</caption>
        <tbody>
          {rows.map((row, index) => (
            <tr key={index}>
              <td className="pr-2 text-right font-semibold text-teal-700">{row.p}</td>
              <td className="border-l border-gray-400 pl-3 text-right text-gray-800">
                {row.n}
              </td>
            </tr>
          ))}
          <tr>
            <td />
            <td className="border-l border-t border-gray-400 pl-3 text-right text-gray-800">
              1
            </td>
          </tr>
        </tbody>
      </table>
      <p className="mt-2 text-center text-sm text-gray-700">
        {n} = {indexFormOf(n)}
      </p>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* venn_primes                                                                */
/* -------------------------------------------------------------------------- */

function VennPrimes({ a, b }: { a: number; b: number }) {
  const { onlyA, shared, onlyB } = useMemo(() => {
    const factorsA = primeFactors(a);
    const factorsB = [...primeFactors(b)];
    const common: number[] = [];
    const leftOnly: number[] = [];
    for (const prime of factorsA) {
      const at = factorsB.indexOf(prime);
      if (at >= 0) {
        common.push(prime);
        factorsB.splice(at, 1);
      } else {
        leftOnly.push(prime);
      }
    }
    return { onlyA: leftOnly, shared: common, onlyB: factorsB };
  }, [a, b]);

  const product = (list: number[]) => list.reduce((acc, value) => acc * value, 1);

  return (
    <div>
      <svg viewBox="0 0 340 190" className="mx-auto block w-full max-w-lg">
        <circle cx="120" cy="95" r="80" className="fill-teal-500/20 stroke-teal-600" />
        <circle cx="220" cy="95" r="80" className="fill-amber-400/20 stroke-amber-500" />
        <text x="60" y="30" fontSize="13" className="fill-teal-700 font-semibold">
          {a}
        </text>
        <text x="265" y="30" fontSize="13" className="fill-amber-600 font-semibold">
          {b}
        </text>
        <text x="78" y="100" textAnchor="middle" fontSize="14" className="fill-gray-800">
          {onlyA.join(" × ") || "—"}
        </text>
        <text x="170" y="100" textAnchor="middle" fontSize="14" className="fill-gray-900 font-semibold">
          {shared.join(" × ") || "—"}
        </text>
        <text x="262" y="100" textAnchor="middle" fontSize="14" className="fill-gray-800">
          {onlyB.join(" × ") || "—"}
        </text>
      </svg>
      <dl className="mt-2 flex justify-center gap-6 text-sm text-gray-700">
        <div>
          <dt className="inline font-semibold">HCF</dt>{" "}
          <dd className="inline">{product(shared)}</dd>
        </div>
        <div>
          <dt className="inline font-semibold">LCM</dt>{" "}
          <dd className="inline">{product(onlyA) * product(shared) * product(onlyB)}</dd>
        </div>
      </dl>
    </div>
  );
}
