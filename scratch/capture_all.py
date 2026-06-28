"""Automated script to capture all 21 dashboard pages with delay and dynamic blurring."""

from __future__ import annotations

import os
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

PAGES = [
    "overview",
    "analysis",
    "portfolio-hub",
    "ask-jayu",
    "risk",
    "signals",
    "trader-lens",
    "promotion",
    "autotrading",
    "toss-account",
    "toss",
    "goal-planner",
    "cashflow",
    "dividend",
    "investor-coach",
    "invest-calendar",
    "data-quality",
    "api-monitoring",
    "simulation-log",
    "run-history",
    "settings"
]


def run_capture():
    project_root = Path(__file__).resolve().parents[3]
    output_dir = project_root / "docs" / "images"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Starting screenshot capture. Target directory: {output_dir}")

    with sync_playwright() as p:
        # Launch headless Chromium
        browser = p.chromium.launch(headless=True)
        # Set large viewport to capture full dashboard
        context = browser.new_context(viewport={"width": 1400, "height": 1100})
        page = context.new_page()

        for idx, page_name in enumerate(PAGES, 1):
            url = f"http://localhost:8765/?page={page_name}"
            print(f"[{idx}/{len(PAGES)}] Visiting {url} ...")
            
            try:
                page.goto(url)
                # 1. Wait 3.5 seconds for API data loading and transitions to finish
                page.wait_for_timeout(3500)
                
                # 2. Inject dynamic blurring on sensitive monetary data and account details
                page.evaluate("""
                    () => {
                        // Blur out any element containing currency symbols, Korean '원', or typical account balance numbers
                        const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null, false);
                        let node;
                        const elementsToBlur = new Set();
                        
                        const moneyPattern = /[\\d,]+\\s*(원|USD|\\$|개|USD)/;
                        const numberPattern = /^\\$?[\\d,]+(\\.\\d+)?$/;
                        
                        while (node = walk.nextNode()) {
                            const val = node.nodeValue.trim();
                            if (moneyPattern.test(val) || numberPattern.test(val)) {
                                const parent = node.parentElement;
                                if (parent && parent.tagName !== 'SCRIPT' && parent.tagName !== 'STYLE') {
                                    elementsToBlur.add(parent);
                                }
                            }
                        }
                        
                        // Also explicitly blur any specific sensitive classes or headers if present
                        document.querySelectorAll('.account-number, #account-summary, .balance, td:nth-child(3), td:nth-child(4)').forEach(el => {
                            elementsToBlur.add(el);
                        });
                        
                        elementsToBlur.forEach(el => {
                            el.style.filter = 'blur(6px)';
                            el.style.opacity = '0.85';
                        });
                    }
                """)
                
                # Take screenshot
                filename = f"jayu_dashboard_{page_name.replace('-', '_')}.png"
                filepath = output_dir / filename
                page.screenshot(path=str(filepath), full_page=False)
                print(f"  Saved screenshot: {filename} ({filepath.stat().st_size} bytes)")
            except Exception as e:
                print(f"  Error capturing {page_name}: {e}")

        browser.close()
    print("Capture process completed successfully!")


if __name__ == "__main__":
    run_capture()
