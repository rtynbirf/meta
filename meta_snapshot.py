#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""meta_snapshot.py — карта вселенной аккаунта GitHub из ПУБЛИЧНОГО API.

Без ключей: только открытые данные, видимые любому. Только stdlib.

Команды:
  snapshot --login USER [--root DIR]   собрать карту → MAP.md + map.json
  drift    --login USER [--root DIR]   пересчитать по API и сверить; exit 1 = враньё
  status   [--root DIR]                печать карты офлайн из map.json

Правило №1: руками счётчик — ЗАПРЕЩЁН. Число живёт только маркером:
  <!--c:имя-->N<!--/c-->
Вписывает snapshot, проверяет drift, краснит CI.

Счётчики — из https://api.github.com/users/{login} и /users/{login}/repos:
  repos        — public_repos профиля
  repos_listed — сколько репо реально пришло постранично (должно сходиться)
  stars        — сумма stargazers_count
  forks        — сумма forks_count
  languages    — число уникальных языков
  pushed_30d   — репо с push за последние 30 дней
  repos_hash   — sha256 отсортированного списка имён (12 знаков): ловит
                 создание, удаление и переименование репозиториев
"""
import argparse
import hashlib
import json
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

TOTALS = ("repos", "repos_listed", "stars", "forks", "languages", "pushed_30d", "repos_hash")
MARKER = re.compile(r"<!--c:([a-z0-9_.-]+)-->([0-9a-f]+)<!--/c-->")


def nvd(v):
    """Счётчика нет в захвате — печатаем «н/д», а не врём нулём."""
    return "н/д" if v is None else v


def api(url):
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json", "User-Agent": "meta-snapshot"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_universe(login, source=None):
    """Живой публичный API; с --source — офлайн-реплей захвата живых данных."""
    if source:
        cap = json.loads(Path(source).read_text(encoding="utf-8"))
        note = "офлайн-реплей захвата живого API от %s" % cap.get("captured_at", "?")
        return cap["profile"], cap["repos"], note
    profile = api("https://api.github.com/users/%s" % login)
    repos, page = [], 1
    while True:
        batch = api("https://api.github.com/users/%s/repos?per_page=100"
                    "&sort=pushed&direction=desc&page=%d" % (login, page))
        if not batch:
            break
        repos.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return profile, repos, ""


def load_universe(root: Path, login: str, source=None):
    """Источник данных: --source → живой API → откат на захват рядом с картой.

    Откат честный: в карту вписывается пометка, откуда числа. Бот при живом
    API заполнит пропуски (звёзды/форки/языки, если их нет в захвате)."""
    if source:
        return fetch_universe(login, source)
    try:
        return fetch_universe(login)
    except Exception as e:
        cap = root / "api-capture.json"
        if cap.exists():
            profile, repos, _ = fetch_universe(login, str(cap))
            return profile, repos, "живой API закрылся (%s) — офлайн-реплей захвата" % e
        raise


def compute(profile, repos):
    names = sorted(r["name"] for r in repos)
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    pushed_30d = 0
    for r in repos:
        when = datetime.fromisoformat(r["pushed_at"].replace("Z", "+00:00"))
        if when >= cutoff:
            pushed_30d += 1
    rows = [{"name": r["name"], "pushed": r["pushed_at"][:10],
             "language": r.get("language") or "—", "stars": r.get("stargazers_count")}
            for r in sorted(repos, key=lambda x: x["name"].lower())]

    def _sum(field):
        vals = [r.get(field) for r in repos]
        return sum(v for v in vals if isinstance(v, int)) \
            if any(isinstance(v, int) for v in vals) else None

    langs = {r.get("language") for r in repos if r.get("language")}
    return {
        "login": profile["login"],
        "repos": profile["public_repos"],
        "repos_listed": len(repos),
        "stars": _sum("stargazers_count"),
        "forks": _sum("forks_count"),
        "languages": len(langs) if langs else None,
        "pushed_30d": pushed_30d,
        "repos_hash": hashlib.sha256("\n".join(names).encode("utf-8")).hexdigest()[:12],
        "rows": rows,
    }


def write_map(root: Path, data, generated: str, note: str = ""):
    core = {"generated_at": generated, "login": data["login"]}
    core.update({k: data[k] for k in TOTALS})
    core["rows"] = data["rows"]
    (root / "map.json").write_text(
        json.dumps(core, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    L = []
    ap = L.append
    ap("# МЕТА-КАРТА ВСЕЛЕННОЙ %s" % data["login"])
    ap("")
    ap("Собрана `meta_snapshot.py` из публичного API GitHub: только данные, видимые любому.")
    ap("Сборка: `%s`. Без ключей, без секретов. Числа — только маркеры; руками счётчик запрещён." % generated)
    if note:
        ap(note + ". Пропуски заполнит бот из живого API.")
    ap("")
    ap("## Итог")
    ap("")
    ap("| Показатель | Значение |")
    ap("|---|---|")
    for k in TOTALS:
        if data[k] is None:
            ap("| %s | н/д (нет в захвате — бот заполнит из живого API) |" % k)
        else:
            ap("| %s | <!--c:%s-->%s<!--/c--> |" % (k, k, data[k]))
    ap("")
    ap("## Репозитории (информационно; бот пересобирает карту)")
    ap("")
    ap("| Репозиторий | Последний пуш | Язык | ★ |")
    ap("|---|---|---|---|")
    for row in data["rows"]:
        stars = "—" if row["stars"] is None else row["stars"]
        ap("| %s | %s | %s | %s |" % (row["name"], row["pushed"], row["language"], stars))
    ap("")
    ap("---")
    ap("*Карту вписал генератор из живого API; подделку ловит `drift` и красный CI.*")
    (root / "MAP.md").write_text("\n".join(L) + "\n", encoding="utf-8")


def read_markers(md: Path) -> dict:
    text = md.read_text(encoding="utf-8")
    return {m.group(1): m.group(2)
            for m in MARKER.finditer(text)}


def expected_markers(data) -> dict:
    return {k: str(data[k]) for k in TOTALS if data.get(k) is not None}


def cmd_snapshot(root: Path, login: str, source=None) -> int:
    profile, repos, note = load_universe(root, login, source)
    data = compute(profile, repos)
    generated = datetime.now(timezone.utc).isoformat(timespec="seconds")
    write_map(root, data, generated, note)
    print("Карта собрана: %s (MAP.md + map.json)" % root)
    print("Сборка %s | репо %s | звёзд %s | форков %s | языков %s | пушей за 30д %s"
          % (generated, data["repos"], nvd(data["stars"]), nvd(data["forks"]),
             nvd(data["languages"]), data["pushed_30d"]))
    if data["repos"] != data["repos_listed"]:
        print("ВНИМАНИЕ: public_repos=%d, а постранично пришло %d — расхождение счётчиков."
              % (data["repos"], data["repos_listed"]))
    return 0


def cmd_drift(root: Path, login: str, source=None) -> int:
    md = root / "MAP.md"
    mj = root / "map.json"
    if not md.exists() or not mj.exists():
        print("Дрейф: карты нет — сначала snapshot.")
        return 1
    profile, repos, _ = load_universe(root, login, source)
    data = compute(profile, repos)
    problems = []
    got = read_markers(md)
    exp = expected_markers(data)
    for k in TOTALS:
        if k not in exp:
            continue  # счётчика нет в источнике (н/д в захвате) — бот заполнит из живого API
        if k not in got:
            problems.append("маркер %s исчез из MAP.md (по API: %s)" % (k, exp[k]))
        elif got[k] != exp[k]:
            problems.append("маркер %s: в карте %s, по API %s" % (k, got[k], exp[k]))
    for k in sorted(set(got) - set(exp)):
        problems.append("маркер %s в карте лишний (значение %s)" % (k, got[k]))
    snap = json.loads(mj.read_text(encoding="utf-8"))
    fresh = {k: data[k] for k in TOTALS}
    if snap.get("login") != data["login"]:
        problems.append("map.json: login %s != %s" % (snap.get("login"), data["login"]))
    if {k: str(snap.get(k)) for k in TOTALS} != {k: str(data.get(k)) for k in TOTALS}:
        problems.append("map.json: счётчики не совпадают с живым API")
    if snap.get("rows") != data["rows"]:
        problems.append("map.json: список репо/даты не совпадают с живым API")
    if problems:
        print("ДРЕЙФ ПОЙМАН — карта врёт API:")
        for p in problems:
            print("  ✗ " + p)
        print("Лечение: python3 meta_snapshot.py snapshot --login %s --root %s" % (login, root))
        return 1
    print("Дрейф: 0. Карта = живому API: репо %s | звёзд %s | языков %s | пушей за 30д %s"
          % (data["repos"], nvd(data["stars"]), nvd(data["languages"]), data["pushed_30d"]))
    return 0


def cmd_status(root: Path) -> int:
    mj = root / "map.json"
    if not mj.exists():
        print("Карты нет: python3 meta_snapshot.py snapshot --login USER --root %s" % root)
        return 1
    snap = json.loads(mj.read_text(encoding="utf-8"))
    print("Мета-карта %s, собрана %s" % (snap.get("login"), snap.get("generated_at")))
    print("Репо: %s (постранично %s) | Звёзд: %s | Форков: %s | Языков: %s | Пушей за 30д: %s"
          % (snap["repos"], snap["repos_listed"], nvd(snap.get("stars")),
             nvd(snap.get("forks")), nvd(snap.get("languages")), snap["pushed_30d"]))
    print("Отпечаток списка репо: %s" % snap["repos_hash"])
    for row in snap["rows"][:10]:
        stars = "—" if row.get("stars") is None else "%d★" % row["stars"]
        print("  %-24s пуш %s | %-10s | %s" % (row["name"], row["pushed"], row["language"], stars))
    if len(snap["rows"]) > 10:
        print("  … и ещё %d" % (len(snap["rows"]) - 10))
    return 0


def main():
    ap = argparse.ArgumentParser(description="мета-карта аккаунта из публичного API")
    ap.add_argument("command", choices=["snapshot", "drift", "status"])
    ap.add_argument("--login", default="rtynbirf", help="аккаунт GitHub")
    ap.add_argument("--root", default=".", help="куда писать/читать MAP.md и map.json")
    ap.add_argument("--source", default=None,
                    help="офлайн-реплей: JSON захвата {captured_at, profile, repos}")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    if args.command == "status":
        return cmd_status(root)
    try:
        if args.command == "snapshot":
            return cmd_snapshot(root, args.login, args.source)
        return cmd_drift(root, args.login, args.source)
    except Exception as e:
        print("API недоступен или ответ неожиданный: %s" % e)
        return 2


if __name__ == "__main__":
    sys.exit(main())
