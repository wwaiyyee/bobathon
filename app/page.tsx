const features = [
  {
    title: "Multi-Agent Pipeline",
    description:
      "Router → Planner → Analyst → Validator → Reporter. Every question is classified, planned, executed, and validated before a single word of output is produced.",
  },
  {
    title: "Evidence-Based Insights",
    description:
      "Every finding is backed by a traceable evidence record. No hallucinated numbers — all claims link back to a recorded computation.",
  },
  {
    title: "3-Layer Validation",
    description:
      "Language lint catches causal overstatement, numerical recomputation verifies correctness, and evidence scoring grades each claim's support level.",
  },
  {
    title: "Tiered Request Budget",
    description:
      "Questions are auto-classified into Lookup, Analysis, Investigation, or Report tiers — each with calibrated compute budgets to avoid over- or under-spending.",
  },
  {
    title: "DuckDB-Powered Analytics",
    description:
      "Fast in-process SQL for aggregations, statistical tests, anomaly detection, and contribution analysis over your uploaded CSV or Excel data.",
  },
  {
    title: "Professional Reports",
    description:
      "Auto-generated 10-section reports: Executive Summary, Key Findings, Anomalies, Methodology, Limitations, and full reproducibility metadata.",
  },
];

export default function Home() {
  return (
    <div className="flex flex-col flex-1 bg-white dark:bg-zinc-950 text-zinc-900 dark:text-zinc-50">
      {/* Hero */}
      <header className="flex flex-col items-center justify-center gap-6 py-24 px-6 text-center border-b border-zinc-100 dark:border-zinc-800">
        <div className="inline-flex items-center gap-2 rounded-full border border-zinc-200 dark:border-zinc-700 px-3 py-1 text-xs font-medium text-zinc-500 dark:text-zinc-400">
          BOBathon Hackathon 2025
        </div>
        <h1 className="text-5xl font-bold tracking-tight max-w-2xl leading-tight">
          Analyx
        </h1>
        <p className="max-w-xl text-lg text-zinc-600 dark:text-zinc-400 leading-relaxed">
          AI-powered analytical intelligence that transforms raw data into
          validated, evidence-based insights through a rigorous multi-agent
          pipeline.
        </p>
        <div className="flex flex-col sm:flex-row gap-3 mt-2">
          <a
            href="http://localhost:8000/docs"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex h-11 items-center justify-center rounded-full bg-zinc-900 dark:bg-zinc-50 px-6 text-sm font-medium text-white dark:text-zinc-900 transition-colors hover:bg-zinc-700 dark:hover:bg-zinc-200"
          >
            API Docs →
          </a>
          <a
            href="https://github.com"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex h-11 items-center justify-center rounded-full border border-zinc-200 dark:border-zinc-700 px-6 text-sm font-medium transition-colors hover:bg-zinc-50 dark:hover:bg-zinc-800"
          >
            View on GitHub
          </a>
        </div>
      </header>

      {/* Features */}
      <main className="flex-1 max-w-5xl mx-auto w-full px-6 py-20">
        <h2 className="text-2xl font-semibold text-center mb-12 text-zinc-800 dark:text-zinc-200">
          What Analyx Does
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
          {features.map((f) => (
            <div
              key={f.title}
              className="rounded-xl border border-zinc-100 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-900 p-6 flex flex-col gap-3"
            >
              <h3 className="font-semibold text-base">{f.title}</h3>
              <p className="text-sm text-zinc-500 dark:text-zinc-400 leading-relaxed">
                {f.description}
              </p>
            </div>
          ))}
        </div>

        {/* Pipeline diagram */}
        <div className="mt-20 text-center">
          <h2 className="text-2xl font-semibold mb-8 text-zinc-800 dark:text-zinc-200">
            Analysis Pipeline
          </h2>
          <div className="flex flex-wrap items-center justify-center gap-2 text-sm font-medium">
            {["Upload", "Route", "Plan", "Execute", "Validate", "Report"].map(
              (step, i, arr) => (
                <span key={step} className="flex items-center gap-2">
                  <span className="rounded-full bg-zinc-900 dark:bg-zinc-50 text-white dark:text-zinc-900 px-4 py-2">
                    {step}
                  </span>
                  {i < arr.length - 1 && (
                    <span className="text-zinc-400">→</span>
                  )}
                </span>
              )
            )}
          </div>
        </div>

        {/* Quick start */}
        <div className="mt-20 rounded-xl border border-zinc-100 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-900 p-8">
          <h2 className="text-xl font-semibold mb-4">Quick Start</h2>
          <ol className="list-decimal list-inside space-y-2 text-sm text-zinc-600 dark:text-zinc-400">
            <li>
              Start the backend:{" "}
              <code className="font-mono text-xs bg-zinc-200 dark:bg-zinc-800 px-1.5 py-0.5 rounded">
                cd insight-os/backend && uvicorn api.main:app --reload --port
                8000
              </code>
            </li>
            <li>
              Start the frontend:{" "}
              <code className="font-mono text-xs bg-zinc-200 dark:bg-zinc-800 px-1.5 py-0.5 rounded">
                npm run dev
              </code>
            </li>
            <li>Open the API at http://localhost:8000/docs to upload a CSV and start asking questions.</li>
          </ol>
        </div>
      </main>

      {/* Footer */}
      <footer className="border-t border-zinc-100 dark:border-zinc-800 py-6 text-center text-xs text-zinc-400 dark:text-zinc-600">
        Built for BOBathon 2025 &mdash; Analyx
      </footer>
    </div>
  );
}
