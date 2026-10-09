"""Exercise all three services in Chromium without cloud models or real user data."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def available_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel", help="Installed browser, e.g. chrome or msedge")
    args = parser.parse_args()
    output = ROOT / "test-results"
    output.mkdir(exist_ok=True)
    processes = []
    logs = []
    with tempfile.TemporaryDirectory(prefix="novelclaw-browser-") as temporary:
        state = Path(temporary)
        ports = {
            name: available_port()
            for name in ("auth-portal", "multiagent", "novelclaw")
        }
        try:
            for name, port in ports.items():
                env = os.environ.copy()
                env.update(
                    {
                        "APP_DATA_DIR": str(state / name),
                        "APP_DATABASE_URL": f"sqlite:///{(state / (name + '.db')).as_posix()}",
                        "APP_AUTH_DATABASE_URL": f"sqlite:///{(state / 'auth-portal.db').as_posix()}",
                        "APP_RUNS_DIR": str(state / name / "runs"),
                        "VECTOR_DB_PATH": str(state / name / "vector_db"),
                        "APP_SESSION_SECRET": "browser-test-session-secret",
                        "APP_SESSION_COOKIE_NAME": "novelclaw_browser_test",
                        "APP_SESSION_COOKIE_DOMAIN": "",
                        "APP_ENCRYPTION_KEY": "",
                        "APP_HTTPS_ONLY": "0",
                        "APP_BASE_PATH": "",
                        "APP_SHARED_PORTAL_URL": "",
                        "APP_MULTIAGENT_URL": "",
                        "APP_CLAW_URL": "",
                        "APP_MULTIAGENT_PORT": str(ports["multiagent"]),
                        "APP_CLAW_PORT": str(ports["novelclaw"]),
                        "APP_SHARED_PORTAL_PORT": str(ports["auth-portal"]),
                        "WEB_UI_LANGUAGE": "zh",
                        "WEB_MODELLESS_MODE": "0",
                        "APP_AGENT_API_KEY": "",
                        "OPENAI_API_KEY": "",
                        "LLM_API_KEY": "",
                        "DEEPSEEK_API_KEY": "",
                        "CODEX_API_KEY": "",
                        "PYTHONUTF8": "1",
                    }
                )
                log = (output / f"{name}.log").open("wb")
                logs.append(log)
                processes.append(
                    subprocess.Popen(
                        [
                            sys.executable,
                            "-m",
                            "uvicorn",
                            "local_web_portal.app.main:app",
                            "--host",
                            "127.0.0.1",
                            "--port",
                            str(port),
                        ],
                        cwd=ROOT / "apps" / name,
                        env=env,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                )
            for name, port in ports.items():
                deadline = time.monotonic() + 25
                while True:
                    try:
                        with urllib.request.urlopen(
                            f"http://127.0.0.1:{port}/healthz", timeout=2
                        ) as response:
                            assert response.status == 200
                        break
                    except OSError:
                        if time.monotonic() > deadline:
                            raise RuntimeError(
                                f"{name} did not start; inspect test-results/{name}.log"
                            )
                        time.sleep(0.2)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    channel=args.channel, headless=True
                )
                context = browser.new_context(
                    viewport={"width": 1440, "height": 1000}, reduced_motion="reduce"
                )
                context.route(
                    "https://fonts.googleapis.com/**", lambda route: route.abort()
                )
                context.route(
                    "https://fonts.gstatic.com/**", lambda route: route.abort()
                )
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                portal = f"http://127.0.0.1:{ports['auth-portal']}"
                claw = f"http://127.0.0.1:{ports['novelclaw']}"
                multi = f"http://127.0.0.1:{ports['multiagent']}"
                page.goto(portal + "/select-mode", wait_until="networkidle")
                page.goto(portal + "/mode-b", wait_until="networkidle")
                assert page.url.startswith(claw), page.url
                for route in (
                    "/console/chat",
                    "/console/models",
                    "/console/mcp",
                    "/console/manuscript/read",
                    "/console/memory/banks",
                ):
                    response = page.goto(claw + route, wait_until="networkidle")
                    assert response.status == 200, route
                    assert page.locator("main").count() == 1, route
                page.goto(claw + "/console/chat", wait_until="networkidle")
                page.keyboard.press("Tab")
                assert page.locator(".skip-link").evaluate(
                    "node => node === document.activeElement"
                )
                page.locator("h1").click()
                page.screenshot(
                    path=str(output / "workspace-desktop.png"), full_page=True
                )
                page.set_viewport_size({"width": 390, "height": 844})
                toggle = page.locator("[data-mobile-nav-toggle]")
                assert toggle.is_visible()
                assert page.locator("#workspace-navigation").evaluate(
                    "node => node.inert"
                )
                toggle.click()
                assert toggle.get_attribute("aria-expanded") == "true"
                page.keyboard.press("Escape")
                assert toggle.get_attribute("aria-expanded") == "false"
                assert page.locator("#workspace-navigation").evaluate(
                    "node => node.inert"
                )
                page.locator("h1").click()
                page.screenshot(
                    path=str(output / "workspace-mobile.png"), full_page=True
                )
                overflow = page.evaluate(
                    "document.documentElement.scrollWidth > window.innerWidth + 1"
                )
                assert not overflow, "Workspace overflows the mobile viewport"
                # Exercise the real reply handler with an unavailable server.
                # The draft must survive a failed POST and remain editable.
                page.set_content(
                    '<section data-idea-copilot-root data-session-id="999"><div data-idea-feed></div><form data-idea-reply-form action="/idea-copilot/999/reply"><textarea name="reply"></textarea><button type="submit">Send</button></form></section>'
                )
                page.add_script_tag(
                    path=str(
                        ROOT
                        / "apps/novelclaw/local_web_portal/app/static/idea_copilot_live.js"
                    )
                )
                page.route(
                    "**/idea-copilot/999/reply",
                    lambda route: route.fulfill(
                        status=503,
                        content_type="application/json",
                        body='{"error":"Temporary failure"}',
                    ),
                )
                page.evaluate(
                    "window.initIdeaCopilotLive(document.querySelector('[data-idea-copilot-root]'))"
                )
                reply = page.locator('textarea[name="reply"]')
                reply.fill("Preserve this writing brief.")
                page.locator('button[type="submit"]').click()
                expect(page.locator("[data-idea-status]")).to_have_text(
                    "Temporary failure"
                )
                expect(reply).to_have_value("Preserve this writing brief.")
                expect(reply).to_be_enabled()
                page.goto(portal + "/mode-a", wait_until="networkidle")
                assert page.url.startswith(multi), page.url
                for route in ("/dashboard", "/providers", "/sessions", "/jobs"):
                    response = page.goto(multi + route, wait_until="networkidle")
                    assert response.status == 200, route
                browser.close()
                assert not errors, errors
                print(
                    json.dumps(
                        {
                            "ok": True,
                            "services": 3,
                            "page_errors": errors,
                            "mobile_overflow": overflow,
                        }
                    )
                )
        finally:
            for process in processes:
                process.terminate()
            for process in processes:
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            for log in logs:
                log.close()


if __name__ == "__main__":
    main()
