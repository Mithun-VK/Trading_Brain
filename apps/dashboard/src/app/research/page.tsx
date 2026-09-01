import { ResearchPanel } from "@/components/ResearchPanel";

export default function ResearchPage() {
  return (
    <>
      <h1>Research Reports</h1>
      <p className="lede">
        Runs the Research Agent: targeted retrieval from Obsidian + PostgreSQL + the
        deterministic quant engine, synthesized by Claude into a structured analysis, then
        published back to Obsidian under 08 Research/.
      </p>
      <ResearchPanel />
    </>
  );
}
