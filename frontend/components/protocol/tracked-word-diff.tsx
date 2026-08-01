import { diffWords } from "@/lib/word-diff";

// Inline word-level rendering for "Änderungen nachverfolgen": reuses the
// existing single-reviewer-color convention (.tracked-strike/.tracked-underline,
// see globals.css) but applies it per changed word instead of to the whole
// block/value, so unchanged words render plainly.
export function TrackedWordDiff({ before, after, className }: { before: string; after: string; className?: string }) {
  const tokens = diffWords(before, after);
  return (
    <span className={className}>
      {tokens.map((token, index) => {
        if (token.op === "equal") return <span key={index}>{token.text}</span>;
        if (token.op === "delete") {
          return (
            <span key={index} className="tracked-strike">
              {token.text}
            </span>
          );
        }
        return (
          <span key={index} className="tracked-underline">
            {token.text}
          </span>
        );
      })}
    </span>
  );
}
