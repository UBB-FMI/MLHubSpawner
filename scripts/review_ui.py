#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SECRETS_FILE = REPO_ROOT / "SECERTS.md"
DEFAULT_SCREENSHOT_DIR = Path("/tmp/mlhub-ui-review")
DEFAULT_WAIT_SECONDS = 60
DEFAULT_WINDOW_WIDTH = 1600
MIN_WINDOW_HEIGHT = 1400
MAX_WINDOW_HEIGHT = 9000


@dataclass
class Credentials:
    url: str
    username: str
    password: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Deploy and visually smoke-check the MLHub JupyterHub UI using Selenium and Chromium.",
    )
    parser.add_argument("--run-make", action="store_true", help="Run `make` in the repository root before opening the browser.")
    parser.add_argument("--url", help="Target MLHub URL. Defaults to the URL stored in SECERTS.md.")
    parser.add_argument("--username", help="Login username. Defaults to SECERTS.md.")
    parser.add_argument("--password", help="Login password. Defaults to SECERTS.md.")
    parser.add_argument("--secrets-file", default=str(DEFAULT_SECRETS_FILE), help="Path to the local markdown file with UI credentials.")
    parser.add_argument("--chromium-binary", default=_which_first("chromium", "chromium-browser", "google-chrome"), help="Path to the Chromium binary.")
    parser.add_argument("--chromedriver", default=_which_first("chromedriver"), help="Path to the chromedriver binary.")
    parser.add_argument("--screenshot-dir", default=str(DEFAULT_SCREENSHOT_DIR), help="Directory where screenshots should be written.")
    parser.add_argument("--wait-seconds", type=int, default=DEFAULT_WAIT_SECONDS, help="Max seconds to wait for login and UI readiness.")
    parser.add_argument("--no-headless", action="store_true", help="Run Chromium with a visible window.")
    return parser.parse_args()


def _which_first(*candidates: str) -> Optional[str]:
    for candidate in candidates:
        resolved = shutil_which(candidate)
        if resolved:
            return resolved
    return None


def shutil_which(binary_name: str) -> Optional[str]:
    return subprocess.run(
        ["bash", "-lc", f"command -v {binary_name} || true"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip() or None


def load_credentials(secrets_path: Path, url_override: Optional[str], username_override: Optional[str], password_override: Optional[str]) -> Credentials:
    url = url_override
    username = username_override
    password = password_override

    if secrets_path.exists():
        secrets_text = secrets_path.read_text()
        url = url or _extract_secret_value(secrets_text, "Test URL")
        username = username or _extract_secret_value(secrets_text, "Username")
        password = password or _extract_secret_value(secrets_text, "Password")

    if not url or not username or not password:
        raise RuntimeError(
            "Missing UI credentials. Provide --url/--username/--password or populate SECERTS.md."
        )

    return Credentials(url=url, username=username, password=password)


def _extract_secret_value(markdown_text: str, key: str) -> Optional[str]:
    pattern = rf"^- {re.escape(key)}:\s*(.+)$"
    match = re.search(pattern, markdown_text, flags=re.MULTILINE)
    if match is None:
        return None
    return match.group(1).strip().strip('"')


def run_make(repo_root: Path):
    subprocess.run(["make"], cwd=repo_root, check=True)


def build_driver(args: argparse.Namespace) -> webdriver.Chrome:
    if not args.chromium_binary:
        raise RuntimeError("Chromium binary not found. Pass --chromium-binary explicitly.")
    if not args.chromedriver:
        raise RuntimeError("chromedriver not found. Pass --chromedriver explicitly.")

    options = Options()
    options.binary_location = args.chromium_binary
    if not args.no_headless:
        options.add_argument("--headless=new")
    options.add_argument(f"--window-size={DEFAULT_WINDOW_WIDTH},{MIN_WINDOW_HEIGHT}")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-gpu")
    options.add_argument("--ignore-certificate-errors")

    service = Service(executable_path=args.chromedriver)
    return webdriver.Chrome(service=service, options=options)


def wait_for_page_ready(driver: webdriver.Chrome, timeout_seconds: int):
    WebDriverWait(driver, timeout_seconds).until(
        lambda current_driver: current_driver.execute_script("return document.readyState") == "complete"
    )


def element_exists(driver: webdriver.Chrome, by: By, selector: str) -> bool:
    try:
        driver.find_element(by, selector)
        return True
    except NoSuchElementException:
        return False


def find_first_present(driver: webdriver.Chrome, selectors):
    for by, selector in selectors:
        try:
            return driver.find_element(by, selector)
        except NoSuchElementException:
            continue
    return None


def maybe_login(driver: webdriver.Chrome, credentials: Credentials, wait_seconds: int):
    if spawn_ui_is_present(driver):
        return

    username_input = find_first_present(
        driver,
        [
            (By.NAME, "username"),
            (By.CSS_SELECTOR, "input[type='email']"),
            (By.ID, "username_input"),
            (By.CSS_SELECTOR, "input[autocomplete='username']"),
        ],
    )
    password_input = find_first_present(
        driver,
        [
            (By.NAME, "password"),
            (By.ID, "password_input"),
            (By.CSS_SELECTOR, "input[type='password']"),
            (By.CSS_SELECTOR, "input[autocomplete='current-password']"),
        ],
    )

    if username_input is None or password_input is None:
        return

    username_input.clear()
    username_input.send_keys(credentials.username)
    password_input.clear()
    password_input.send_keys(credentials.password)

    submit_button = find_first_present(
        driver,
        [
            (By.ID, "login_submit"),
            (By.CSS_SELECTOR, "input[type='submit']"),
            (By.CSS_SELECTOR, "button[type='submit']"),
        ],
    )
    if submit_button is not None:
        submit_button.click()
    else:
        password_input.send_keys(Keys.RETURN)

    WebDriverWait(driver, wait_seconds).until(lambda current_driver: spawn_ui_is_present(current_driver))


def spawn_ui_is_present(driver: webdriver.Chrome) -> bool:
    if element_exists(driver, By.ID, "machineSelect"):
        return True
    return element_exists(driver, By.CSS_SELECTOR, ".machine-card") and element_exists(driver, By.CSS_SELECTOR, ".mlhub-shell")


def load_spawn_ui(driver: webdriver.Chrome, credentials: Credentials, wait_seconds: int):
    deadline = time.time() + wait_seconds
    last_error = None

    while time.time() < deadline:
        try:
            driver.get(credentials.url)
            wait_for_page_ready(driver, min(20, wait_seconds))
            maybe_login(driver, credentials, min(20, wait_seconds))
            maybe_open_spawn_page(driver, min(20, wait_seconds))
            WebDriverWait(driver, min(20, wait_seconds)).until(lambda current_driver: spawn_ui_is_present(current_driver))
            return
        except TimeoutException as error:
            last_error = error
            time.sleep(3)

    raise RuntimeError(f"Timed out waiting for the spawn UI at {credentials.url}. Last error: {last_error}")


def collect_ui_summary(driver: webdriver.Chrome) -> dict:
    machine_cards = driver.find_elements(By.CSS_SELECTOR, ".machine-card")
    health_rows = driver.find_elements(By.CSS_SELECTOR, ".health-item")

    selected_machine = ""
    for selector in (".machine-card.is-active .machine-card-name", ".selected-profile-title"):
        try:
            selected_machine = driver.find_element(By.CSS_SELECTOR, selector).text.strip()
            if selected_machine:
                break
        except NoSuchElementException:
            continue

    summary = {
        "title": driver.title,
        "url": driver.current_url,
        "machine_card_count": len(machine_cards),
        "health_row_count": len(health_rows),
        "selected_machine": selected_machine,
    }

    return summary


def maybe_open_spawn_page(driver: webdriver.Chrome, wait_seconds: int):
    if spawn_ui_is_present(driver):
        return

    start_button = find_first_present(
        driver,
        [
            (By.ID, "start"),
            (By.CSS_SELECTOR, "a[href*='/spawn/']"),
        ],
    )
    if start_button is None:
        return

    spawn_href = start_button.get_attribute("href")
    if spawn_href:
        driver.get(spawn_href)
    else:
        start_button.click()
    wait_for_page_ready(driver, wait_seconds)


def save_screenshot(driver: webdriver.Chrome, screenshot_dir: Path) -> Path:
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    screenshot_path = screenshot_dir / f"mlhub-ui-{timestamp}.png"

    total_height = driver.execute_script(
        "return Math.max(document.body.scrollHeight, document.documentElement.scrollHeight);"
    )
    total_width = driver.execute_script(
        "return Math.max(document.body.scrollWidth, document.documentElement.scrollWidth);"
    )
    window_height = max(MIN_WINDOW_HEIGHT, min(int(total_height) + 180, MAX_WINDOW_HEIGHT))
    window_width = max(DEFAULT_WINDOW_WIDTH, int(total_width) + 40)
    driver.set_window_size(window_width, window_height)
    time.sleep(0.5)
    driver.save_screenshot(str(screenshot_path))
    return screenshot_path


def save_failure_artifacts(driver: webdriver.Chrome, screenshot_dir: Path) -> dict:
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    screenshot_path = screenshot_dir / f"mlhub-ui-failure-{timestamp}.png"
    html_path = screenshot_dir / f"mlhub-ui-failure-{timestamp}.html"
    driver.save_screenshot(str(screenshot_path))
    html_path.write_text(driver.page_source)
    return {
        "failure_screenshot": str(screenshot_path),
        "failure_html": str(html_path),
        "failure_url": driver.current_url,
        "failure_title": driver.title,
    }


def main() -> int:
    args = parse_args()
    credentials = load_credentials(
        secrets_path=Path(args.secrets_file),
        url_override=args.url,
        username_override=args.username,
        password_override=args.password,
    )

    if args.run_make:
        run_make(REPO_ROOT)

    driver = build_driver(args)
    try:
        load_spawn_ui(driver, credentials, args.wait_seconds)
        summary = collect_ui_summary(driver)
        screenshot_path = save_screenshot(driver, Path(args.screenshot_dir))
    except Exception as error:
        failure_artifacts = save_failure_artifacts(driver, Path(args.screenshot_dir))
        print(
            json.dumps(
                {
                    "error": str(error),
                    "failure": failure_artifacts,
                },
                sort_keys=True,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 1
    finally:
        driver.quit()

    print(json.dumps({"summary": summary, "screenshot": str(screenshot_path)}, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
