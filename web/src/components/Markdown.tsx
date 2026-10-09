import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { memo } from "react";

const CITATION = /\[([^[\]\n]{3,400})\]/g; // paper titles can be long
const isDocument = (text: string) => /\b(page|p\.)\s*\d+|\.pdf\b/i.test(text);

/**
 * Turns literal "[Title, Journal, Date]" / "[file.pdf, Page 2]" citations the
 * model writes into <cite> chips. Real links were already parsed by remark, so
 * only plain-text brackets are left in text nodes.
 */
function remarkCitations() {
  const walk = (node: any) => {
    if (!node.children || node.type === "code" || node.type === "inlineCode") return;
    const next: any[] = [];
    for (const child of node.children) {
      if (child.type !== "text") {
        walk(child);
        next.push(child);
        continue;
      }
      let last = 0;
      for (const match of child.value.matchAll(CITATION)) {
        const index = match.index ?? 0;
        if (index > last) next.push({ type: "text", value: child.value.slice(last, index) });
        next.push({
          type: "citation",
          data: { hName: "cite", hProperties: { className: isDocument(match[1]) ? "cite cite-doc" : "cite cite-paper" } },
          children: [{ type: "text", value: match[1] }],
        });
        last = index + match[0].length;
      }
      if (last === 0) next.push(child);
      else if (last < child.value.length) next.push({ type: "text", value: child.value.slice(last) });
    }
    node.children = next;
  };
  return (tree: any) => walk(tree);
}

const components = {
  a: (props: any) => <a {...props} target="_blank" rel="noreferrer noopener" />,
  table: (props: any) => (
    <div className="table-wrap">
      <table {...props} />
    </div>
  ),
};

export const Markdown = memo(function Markdown({ text }: { text: string }) {
  return (
    <div className="prose" dir="auto">
      <ReactMarkdown remarkPlugins={[remarkGfm, remarkCitations]} components={components}>
        {text}
      </ReactMarkdown>
    </div>
  );
});
