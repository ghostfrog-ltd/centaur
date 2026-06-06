<?php
declare(strict_types=1);

function centaurNavigationItems(): array
{
    return [
        ['label' => 'Slot Compounding', 'href' => '/'],
        ['label' => 'Slot Numbers', 'href' => '/slot-economics.php'],
        ['label' => 'Score Numbers', 'href' => '/score-numbers.php'],
        ['label' => 'Fitness Explainer', 'href' => '/fitness-explainer.php'],
        ['label' => 'Proposal Counts', 'href' => '/proposal-counts.php'],
        ['label' => 'Last Day Trades', 'href' => '/recent-trades.php'],
        ['label' => 'Profit Lock Review', 'href' => '/profit-lock-review.php'],
        ['label' => 'Flow Map', 'href' => '/flow.php'],
        ['label' => 'Commands', 'href' => '/commands.php'],
        ['label' => 'Glossary', 'href' => '/glossary.php'],
        ['label' => 'Dashboard', 'href' => '/dashboard.php'],
        ['label' => 'Live JSON', 'href' => '/snapshot/'],
        ['label' => 'Download Plan', 'href' => '/reports/50-dollar-day-plan.md', 'download' => true],
    ];
}

function centaurNavigationEscape(string $value): string
{
    return htmlspecialchars($value, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
}

function centaurRenderNavigation(string $currentHref): void
{
    static $renderedAssets = false;
    $menuId = 'centaur-nav-' . preg_replace('/[^a-z0-9]+/', '-', strtolower(trim($currentHref, '/') ?: 'home'));

    if (!$renderedAssets) {
        $renderedAssets = true;
        ?>
        <style>
          .centaur-menu {
            display: inline-flex;
            position: relative;
          }

          .centaur-menu-toolbar {
            align-self: flex-start;
            align-items: flex-start;
          }

          .centaur-menu-toggle {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 44px;
            height: 44px;
            border: 1px solid rgba(15, 139, 141, 0.28);
            border-radius: 8px;
            background: #ffffff;
            color: #172022;
            cursor: pointer;
            box-shadow: 0 8px 22px rgba(18, 31, 32, 0.08);
          }

          .centaur-menu-toggle:hover,
          .centaur-menu-toggle:focus-visible {
            border-color: rgba(15, 139, 141, 0.58);
            outline: none;
          }

          .centaur-menu-icon,
          .centaur-menu-icon::before,
          .centaur-menu-icon::after {
            display: block;
            width: 18px;
            height: 2px;
            border-radius: 999px;
            background: currentColor;
            content: "";
          }

          .centaur-menu-icon {
            position: relative;
          }

          .centaur-menu-icon::before,
          .centaur-menu-icon::after {
            position: absolute;
            left: 0;
          }

          .centaur-menu-icon::before {
            top: -6px;
          }

          .centaur-menu-icon::after {
            top: 6px;
          }

          .centaur-menu-popout {
            position: fixed;
            top: 0;
            right: 0;
            z-index: 80;
            display: flex;
            flex-direction: column;
            gap: 8px;
            width: min(360px, calc(100vw - 28px));
            height: 100vh;
            padding: 18px;
            border-left: 1px solid #d7e1dc;
            background: rgba(255, 255, 255, 0.98);
            box-shadow: -22px 0 46px rgba(18, 31, 32, 0.16);
            transform: translateX(100%);
            transition: transform 160ms ease;
          }

          .centaur-menu[data-open="true"] .centaur-menu-popout {
            transform: translateX(0);
          }

          .centaur-menu-head {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 16px;
            margin-bottom: 6px;
          }

          .centaur-menu-title {
            color: #096669;
            font-size: 12px;
            font-weight: 800;
            letter-spacing: 0.08em;
            text-transform: uppercase;
          }

          .centaur-menu-close {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 36px;
            height: 36px;
            border: 1px solid #d7e1dc;
            border-radius: 8px;
            background: #ffffff;
            color: #172022;
            cursor: pointer;
            font-size: 24px;
            line-height: 1;
          }

          .centaur-menu-link {
            display: flex;
            align-items: center;
            min-height: 44px;
            border: 1px solid #d7e1dc;
            border-radius: 8px;
            padding: 0 13px;
            background: #ffffff;
            color: #172022;
            font-size: 14px;
            font-weight: 760;
            text-decoration: none;
          }

          .centaur-menu-link:hover,
          .centaur-menu-link:focus-visible {
            border-color: rgba(15, 139, 141, 0.58);
            outline: none;
          }

          .centaur-menu-link[aria-current="page"] {
            border-color: #0f8b8d;
            background: #0f8b8d;
            color: #ffffff;
          }

          .centaur-menu-backdrop {
            position: fixed;
            inset: 0;
            z-index: 70;
            display: none;
            background: rgba(18, 31, 32, 0.28);
          }

          .centaur-menu[data-open="true"] .centaur-menu-backdrop {
            display: block;
          }
        </style>
        <script>
          document.addEventListener("click", (event) => {
            const toggle = event.target.closest("[data-centaur-menu-toggle]");
            const close = event.target.closest("[data-centaur-menu-close]");
            const backdrop = event.target.closest("[data-centaur-menu-backdrop]");

            if (toggle) {
              const menu = toggle.closest("[data-centaur-menu]");
              const nextOpen = menu.dataset.open !== "true";
              menu.dataset.open = nextOpen ? "true" : "false";
              toggle.setAttribute("aria-expanded", nextOpen ? "true" : "false");
              if (nextOpen) {
                const firstLink = menu.querySelector(".centaur-menu-link");
                if (firstLink) firstLink.focus();
              }
              return;
            }

            if (close || backdrop) {
              const menu = (close || backdrop).closest("[data-centaur-menu]");
              const menuToggle = menu.querySelector("[data-centaur-menu-toggle]");
              menu.dataset.open = "false";
              menuToggle.setAttribute("aria-expanded", "false");
              menuToggle.focus();
            }
          });

          document.addEventListener("keydown", (event) => {
            if (event.key !== "Escape") return;
            document.querySelectorAll('[data-centaur-menu][data-open="true"]').forEach((menu) => {
              const menuToggle = menu.querySelector("[data-centaur-menu-toggle]");
              menu.dataset.open = "false";
              menuToggle.setAttribute("aria-expanded", "false");
              menuToggle.focus();
            });
          });
        </script>
        <?php
    }
    ?>
    <nav class="centaur-menu" data-centaur-menu data-open="false" aria-label="Primary navigation">
      <button class="centaur-menu-toggle" type="button" aria-label="Open navigation" aria-expanded="false" aria-controls="<?= centaurNavigationEscape($menuId) ?>" data-centaur-menu-toggle>
        <span class="centaur-menu-icon" aria-hidden="true"></span>
      </button>
      <div class="centaur-menu-backdrop" data-centaur-menu-backdrop></div>
      <div id="<?= centaurNavigationEscape($menuId) ?>" class="centaur-menu-popout">
        <div class="centaur-menu-head">
          <div class="centaur-menu-title">Navigation</div>
          <button class="centaur-menu-close" type="button" aria-label="Close navigation" data-centaur-menu-close>&times;</button>
        </div>
        <?php foreach (centaurNavigationItems() as $item): ?>
          <?php
            $href = (string) $item['href'];
            $isCurrent = $href === $currentHref;
          ?>
          <a
            class="centaur-menu-link"
            href="<?= centaurNavigationEscape($href) ?>"
            <?= $isCurrent ? 'aria-current="page"' : '' ?>
            <?= ($item['download'] ?? false) ? 'download' : '' ?>
          ><?= centaurNavigationEscape((string) $item['label']) ?></a>
        <?php endforeach; ?>
      </div>
    </nav>
    <?php
}
