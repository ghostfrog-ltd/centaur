<?php
declare(strict_types=1);

header('Cache-Control: no-store, no-cache, must-revalidate, max-age=0');
header('Pragma: no-cache');

require __DIR__ . '/navigation.php';

function flowReadMermaid(string $relativePath): string
{
    $path = dirname(__DIR__) . '/' . ltrim($relativePath, '/');
    if (!is_readable($path)) {
        return 'flowchart TD' . PHP_EOL . '  missing["Missing Mermaid file: ' . $relativePath . '"]' . PHP_EOL;
    }
    return (string) file_get_contents($path);
}

function flowEscape(string $value): string
{
    return htmlspecialchars($value, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
}

$diagrams = [
    [
        'title' => 'Current Control Pipeline',
        'description' => 'Generated from app.framework.engine.pipelines.build_default_pipeline(); nodes show ownership lanes and runner code references.',
        'path' => 'docs/visuals/current_pipeline.mmd',
        'mermaid' => flowReadMermaid('docs/visuals/current_pipeline.mmd'),
    ],
    [
        'title' => 'Entry Decision Funnel',
        'description' => 'Conceptual map from configured symbols to candidates, signals, fitness, CFO, and execution.',
        'path' => 'docs/visuals/entry_decision_funnel.mmd',
        'mermaid' => flowReadMermaid('docs/visuals/entry_decision_funnel.mmd'),
    ],
    [
        'title' => 'Learning System',
        'description' => 'Detailed map of the autonomous learning lane: heartbeat trigger, replay readiness, evidence generation, operator alerts, and fail-closed promotion boundaries.',
        'path' => 'docs/visuals/learning_system_flow.mmd',
        'mermaid' => flowReadMermaid('docs/visuals/learning_system_flow.mmd'),
    ],
];
?>
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Centaur Flow Map</title>
  <script type="module">
    import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs";

    mermaid.initialize({
      startOnLoad: true,
      securityLevel: "loose",
      theme: "base",
      themeVariables: {
        primaryColor: "#eef5f1",
        primaryTextColor: "#172022",
        primaryBorderColor: "#0f8b8d",
        lineColor: "#657174",
        secondaryColor: "#fff8e6",
        tertiaryColor: "#f7fbff",
        fontFamily: "Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
      },
      flowchart: {
        curve: "basis",
        htmlLabels: true,
        nodeSpacing: 34,
        rankSpacing: 46
      }
    });
  </script>
  <style>
    :root {
      color-scheme: light;
      --bg: #f4f7f5;
      --surface: #ffffff;
      --surface-2: #eef5f1;
      --ink: #172022;
      --muted: #657174;
      --line: #d7e1dc;
      --teal: #0f8b8d;
      --teal-dark: #096669;
      --gold: #b78313;
      --shadow: 0 16px 40px rgba(18, 31, 32, 0.08);
    }

    * {
      box-sizing: border-box;
    }

    body {
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }

    .shell {
      width: min(1440px, calc(100% - 32px));
      margin: 0 auto;
      padding: 24px 0 36px;
    }

    .topbar {
      display: flex;
      align-items: end;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 18px;
    }

    .eyebrow {
      margin: 0 0 7px;
      color: var(--teal-dark);
      font-size: 12px;
      font-weight: 800;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }

    h1 {
      margin: 0;
      font-size: clamp(28px, 3vw, 44px);
      line-height: 1.02;
      letter-spacing: 0;
    }

    .lede {
      max-width: 900px;
      margin: 10px 0 0;
      color: var(--muted);
      line-height: 1.55;
    }

    .toolbar {
      display: flex;
      flex-wrap: wrap;
      justify-content: flex-end;
      gap: 10px;
    }

    .button {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 40px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
      color: var(--ink);
      cursor: pointer;
      font-weight: 750;
      padding: 0 14px;
      box-shadow: 0 6px 18px rgba(18, 31, 32, 0.05);
      text-decoration: none;
    }

    .button.primary {
      background: var(--teal);
      border-color: var(--teal);
      color: white;
    }

    .button:hover {
      border-color: rgba(15, 139, 141, 0.45);
    }

    .grid {
      display: grid;
      gap: 18px;
    }

    .panel {
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: rgba(255, 255, 255, 0.92);
      box-shadow: var(--shadow);
    }

    .panel-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      border-bottom: 1px solid var(--line);
      padding: 14px 16px;
      background: rgba(255, 255, 255, 0.76);
    }

    .panel-title {
      margin: 0;
      font-size: 17px;
      font-weight: 850;
    }

    .panel-desc {
      margin: 4px 0 0;
      color: var(--muted);
      font-size: 13px;
    }

    .badge {
      display: inline-flex;
      align-items: center;
      min-height: 28px;
      border-radius: 999px;
      padding: 4px 10px;
      background: var(--surface-2);
      color: var(--teal-dark);
      font-size: 12px;
      font-weight: 800;
      white-space: nowrap;
    }

    .diagram-wrap {
      min-width: 960px;
      padding: 18px;
    }

    .mermaid {
      display: flex;
      justify-content: center;
      margin: 0;
      font-size: 14px;
    }

    .note {
      margin: 0 0 18px;
      border-left: 4px solid var(--gold);
      border-radius: 8px;
      background: #fff8e6;
      padding: 12px 14px;
      color: #5f4a19;
      line-height: 1.5;
    }

    code {
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
    }

    @media (max-width: 760px) {
      .topbar {
        align-items: stretch;
        flex-direction: column;
      }

      .toolbar {
        justify-content: flex-start;
      }
    }
  </style>
</head>
<body>
  <main class="shell">
    <header class="topbar">
      <div>
        <p class="eyebrow">Project Centaur</p>
        <h1>Flow Map</h1>
        <p class="lede">Rendered Mermaid views of the current control pipeline, the entry decision funnel, and the autonomous learning system, with each diagram tied back to code ownership and safety boundaries.</p>
      </div>
      <div class="toolbar centaur-menu-toolbar">
        <?php centaurRenderNavigation('/flow.php'); ?>
      </div>
    </header>

    <p class="note">Update generated Mermaid files with <code>.venv-mac/bin/python scripts/update_mermaid_visuals.py</code> after changing orchestration, graph nodes, or pipeline order. Generated flow diagrams must show source ownership so the visual stays married to the code and <code>app/</code> folder structure.</p>

    <section class="grid" aria-label="Centaur flow diagrams">
      <?php foreach ($diagrams as $diagram): ?>
        <article class="panel">
          <header class="panel-head">
            <div>
              <h2 class="panel-title"><?= flowEscape($diagram['title']) ?></h2>
              <p class="panel-desc"><?= flowEscape($diagram['description']) ?></p>
            </div>
            <span class="badge"><?= flowEscape($diagram['path']) ?></span>
          </header>
          <div class="diagram-wrap">
            <pre class="mermaid"><?= flowEscape($diagram['mermaid']) ?></pre>
          </div>
        </article>
      <?php endforeach; ?>
    </section>
  </main>
</body>
</html>
