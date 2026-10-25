"""Apply the consistent dashboard surfaces for the vehicle overview. Run in your dkss repository; --check is read-only."""
import argparse
import ast
import base64
from datetime import datetime
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zlib

PAYLOAD = 'eNrNG81y27j57qfAyJOJtRJl/ouUI0/aXvawOXUmh71kQAAUGVMkh6Rkq5lc+wB9md77KH2SfgBIin8SqbTb3UwsWRDx/f8DpqHvI0XZhQXCj3mBi5A8kjx/PLIgJBH78oKzgn1Jjiw7hux1BV8hb9pzd2FM2RvSHephX1utXNvwLMNAmqrapnmnKMpUjHeLxWIy1o8fkaItLbTgLx8/3qHHn9Bn+TiqHtwgDuuQL9EhJck+jHfoNclelgjHFMFCikmBjmF+wBHKD/s9zkKWr9BPj3fKfYlaqWApKd4x9A1k+JIoYfyyudcNwzbpk1zZHwpGN/eWa3uOWq5FYcw295Qwk1WPedEBlnTH8l1WLqU4giXf8h2fPCEgUnkNaRFsAApJoiTbHHH2UGGdP6Hvd4vfizixRHBGlbeNZqZv08hFF8j9CQj2kjclD/8Gmtl4SUZZpsBKe5PQfb0VbcL8AS+9Q1Ek8VIq7TTf+Ak55AqoMvQiLojkUAgG9fQN5UkUUnRvEsfw9KfqKyXx/ZwVGyO9jg8vL36z4fhAsoBPsn6vE9t28RMq2FuhUEaSDEw5iTdxEjOOhRutoS01MFv5xg33gnhWIEIaggHHhClFhskLCgGTlPaaUx2wcBcU8ncpvSa/joldQqtvlAzT8JBvLPXdNZ0MIH1GeYpjwFyi0zk6P2JgAgAcnthlySGmGy5UnCk7jojFxYOrUrZb3hOXeowt7x0LyCHzq7L+hgB3GuHTZpeFQPoOpxtN7dlZiikFi1GKpPr6e8NhOzBX3F4BcgsCGM0ujBuwNhqXnLTpUpRaLcraojmL865EpfjPcngNwCaepGUHmCavtfYX/wsaa2KkH84H6OVebTG/S6gzSqiKDC4FjgYCiGnYtkqvKoybS0iSuLZLzW4YpvwgTEWKoNJuGAsP9KKEvDwhAAbxHkcKjsJdvNmHlEbsuk4BbcAwF0rDZjiiJySAKMDZPt8QsEOWPaGvh7wI/ZMClBawtAGDBvP2WPHKWNwys1LmSEVyoRI9X3EaxqHWwvUSiET7rvR97brCf2MGFKFDkCl5UDQItF2jmXfYc64Z1hivfUsDl0D8B6TWsrh7Rn3Dx6MmVYmGx/rAWK4ylh+iAhKKnyhFWERsPklqXCxCaT6IjacZViUngVJAEssQiVPOsLDKynhXplXufJUrtqo+jbmo2pRalRRUw7bUyUw/IwzcnUnWtI4XTYPT9kvdbPil3ghzreDQjr7wKxhZW6QdZZq8KijZtMw1xe4oeQQ2Fw31tWNBBausVJrofBXQub181jRjbvR2rfBSbSZXW0Oc6kjC50TKshHesjDtZyV4VUAqsAT7gOLDPs43GUsZLh6MJVjIHr89qEvNz+bzhhWOBLQSZxGKAmaadUtmWlLy/R/LYM1QIMEOlnMt+79U5ix+Lz678Shivqjw6hqQOZZHB22/z/9oYvxxAaGJAtoE/BtRJwuCS/dwMPYIvgUQRBUaHrslxsh+vrEKI+OhoQw0TjPQOJ3Q1Za73VVqJ6JUnYism013qaloId9adfMI6zUr8WHvgTTzPY6iXgSqorm0GaudNmQMHhEXOzEvS5pVbBnUerG8G506hiTatV46spr5ZiIpRbjnTtbkbD3M2dXQBK0WU1IWl/VKxw+Jbz11DJS51CfOaCi4Dhf7ag8uBrhuy72rrzzLwcYEm26i7Bp5iwDP1yiubRHrjm26t4GH9JEIxiq3JTY1zGnSpjjeSc9vC8X27Z5Q1kQ0elOE/QNgB2SNsWlb5jRhlBivihozk9m1qD0ol2x6E/SupLFh+tZUbSXQxIdHdpVEiEw2r+mr+sRzvPW6ikxrfakZaCHfxiITuOXlUs/shgdRc45WVLEfZntGOWyU1v7Ogxhq1z6id+eb/QjIeM0gteL49BqwjN2IpgqiF0LXjQEGE54eFTnV6ReHsjjoNkFV4rlUNLjV4KAMoYY62N3fY0pM6k9LTv65UODSdTvBVD/XTffa2vQd71INwFmC6iLjwzp11Hd/V/k4HkjIHyy8m/KhPkiI/mbyQZPlcy6aBkqLdoxzNU8lpG2e/YEY8L9jF1sWKPbLikpT+XCt22r0sn2/yxysY0W8acvc7FXBmm/5uNc2VSowqn7o8sz4j80fcxjzz5nBVC137Qzyh8b4E2ZScMcIhQtVOVm1NY32eguXub18SKjvjYdJfsAgxjMT+8Zzu7gyoWFErfax2f003RjK26wYJSXNEkhuOMoHB6tTetIKQt2BNHXIVOb65tWG/Grf1u/OdEflEu70KIvbKFRvpUiF1E5vJWqS4G+a8Z01PRW6IPiW3qw/BOr1Zi0ndZjl6x2PxL7ue4MddDfnV0GJOgYmt5c1PSHKaqmlh+oYooHaaqCuJm8t1HzhcgnE6znXXa7RQryOVXM4TZMwLvY830J1lEOJHIQRn+U3DykmJLAGnAg3wLQnr43Dj/PKDaBlZhTVHI6gS8EZ75T3aX/CQDEh3mh86EFpm7lI4jTMmEjPGxnypk24q3WhYT59N4fPZu6pB5nEGK1OmuerpQeYrbmP0c2Tf0x2iQu1mDbKrnBTOs4uuoHd57ro75YAnfLjNrB17ybOoxSROyEkcc/sTYIaiAU3nVLjB3qnQVou8dmco+hSgOIawloEDPnGIwYg/QiNUogfzsXT2gYQc/TtDvF/1063W1XEUkyzDuDDWaHwAL+UvVguP/GDkLG6QtQR4MjX8FYnkM2jRuEOUza1rgXorWw7fGL5/boQBibwV2fu+uDM3S0tfCKmch49XGXdAKMdvgXdktyNhh7BVobjgTQkXTe4Ick3bkjiVstfA5wxigRaVCXDIgPORUyvLrIsUcR2/PpDdb0lzsOcBxfI/kWAAviQZCdxu2XSOVRggMc3Dnh7Q9nrHX0o1N056Wxls7oJ8zyHeuM98DDEZtCzmd+oTdpYPEo15v2XA7yyWfihuLmcnKbFQed5m7AMw1gaYBnwpjk3VSVDzXCVDMcqMFjilpzmCA831WWW6TTVzHOpc2PPPuECT2V5nQs8VaS6W4Cv/AnloDiAkB8ynzdhtZ9AMM8QD+s1ESmOWZQ/oTCOgbMsec35dbET5GBcCDdZTJ8dfhsak5q2o9vOLQditZSHhyJXT6S0H8FUW3gXIeiXZfJcRHxVf+7cm7ouo3DP+B7I05u4CGRUfGBHFs8vWGS7rIEyCPgz5RhzOq5G9Z2JSsCZQKvPJ78RBMnpxI4FrIZHx0kREnah8m63xxo1e6MHm7gOm9wLC1WDKjmW01VBN5rlbt8Lm9wJUbnu0vwkKZpHldD3VOQTjxJGp16IGRq/0zVbN+Zc5xy0mH6joho7Uou4nXbUUsftCzTIypiVizKtvIK48op4vpxKSD3BHbgeRptXdKtap3MHdhUU+wh5V78uL+R6GiGuTVcry1JtQvT2hdyrAOQ93KuPiBNZXqyYZany7R2UxyRLEFffQ4z3bI7eff+QH3eIQEmUb2dlKTFDXC5/Tt62M97o6Cb8nyFwv2g746KYiaD0wrYzcsgycJ6/cMVVq7Ka3s60lW3Va9zvCU63M2EureWv4IL1Os5CrAQhpQzWiuzAZs9AdugjTi7abtH7yjnfc9p5I4eATGOGTtsZoKtwO7NyigK/2zOUiWcenz+kGAotup19WiPjaO41VTGP5id+FTrQnL2iGcgK9L2J1ECHxwE1RKwG8iJJIoG4hqOZyMIWsvhNKqQqNrJ/AWg2NpAhl5CJzMhSGg8hW7EjBZYVQzHg1fx1CBXhs12Bi4QZvzJNgAdNnyFyku/Zdua2WNJ0tD5akYEGSefRs0e68bONdaSXxMNvR808L8C7Hmh6c0HRP7uRAgz8uofPRzuwPzlIMwKQnYPMwBrCzIuUvIV6D6QayEWWIn4UC8HPr3v+6ehG8Mo/f3bKBdCVtXL48qCcAlbKqYZuQtYFGNYvOsh6aA+YUFYMUKSpSHN+1n/hHziD9tGCVyNYqVoFJmctGYJrgOWsP9mg88/u3kbrzya8avpRqaiFQtXnex7B0coF6Ybvvjd8UsatL1DjPPC+Q3gm5MmzY7YO92bPH8SV3/PXBc5flPy095IIXOab9HFpr3P0nWOH558/0PAoXho7G8edABajIGP+dsZBAB0r8NAX2C9higXssUhAxD0i5DFFc4x/3icrmwYpj5wW6dziAcoKHEZCuvWmco1vSlvCFIX3+TGIgfAQ+tc/UbXknSQq8ZzEBbydSW3VtrMxpmMosDgCyfBAkPr33/9R8wVyeYzCIVWL8xpUTpT4ovJBoMoYRNa8OEUsDxgrGuQcsugLlMUP7+WfXLxf8jDMuCFv31//8wt49Lh9r6u6ram6BYVjzntaTVjD7Plu8X/DXNb5+Rk3EhYYgv8MngjxJ7hdxCQ6UIZmbUzcVFkmUtyskuuFRwvs5ecHy7mxJebGVpURe1vDOE/lePAL5FZ44T1IG11lhcCIMCxQY06yMC1QnpFR4X29KLuv15WGKPNZBsYlkXEd/jZouxrrIS6FIM0Z5PAfwjLq1A=='
FILES = ['static/css/vehicle_karte_overview.css', 'templates/vehicle_karte.html']
VERSION = "overview-surfaces-v23-20261025"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path.cwd()
    if not (root / "app.py").is_file() or not (root / ".git").exists():
        raise RuntimeError("Run this script from C:\\Users\\takah\\dkss.")
    if not shutil.which("git"):
        raise RuntimeError("git is required. No files were changed.")
    payload = zlib.decompress(base64.b64decode(PAYLOAD))
    def apply(cwd, *options):
        return subprocess.run(["git", "apply", *options, "-"], cwd=cwd, input=payload,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    check = apply(root, "--check")
    if check.returncode:
        if not apply(root, "--reverse", "--check").returncode:
            print("ALREADY_APPLIED:", VERSION)
            print("Restart Flask, then press Ctrl+F5 on Overview.")
            return
        raise RuntimeError("Patch does not match your current files. No files were changed.\n"
                           + check.stderr.decode("utf-8", "replace"))
    original = {name: (root / name).read_bytes() if (root / name).exists() else None for name in FILES}
    # Verify the predicted Python sources before modifying the real working tree.
    with tempfile.TemporaryDirectory(prefix="dkss-overview-surfaces-check-") as folder:
        staging = Path(folder)
        for name, data in original.items():
            if data is not None:
                target=staging / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
        prepared = apply(staging, "--whitespace=nowarn")
        if prepared.returncode:
            raise RuntimeError("Staging validation failed. No files were changed.\n"
                               + prepared.stderr.decode("utf-8", "replace"))
        for name in FILES:
            if name.endswith(".py"):
                ast.parse((staging / name).read_text(encoding="utf-8-sig"), filename=name)
    print("PATCH_VERSION:", VERSION)
    print("PYTHON_SYNTAX_OK; NO_AI_REQUESTS; NO_DB_CHANGES")
    if args.check:
        print("CHECK_OK; no application files changed")
        return
    # Refuse to overwrite code changed since validation began.
    for name, data in original.items():
        current=(root / name).read_bytes() if (root / name).exists() else None
        if current != data:
            raise RuntimeError("A file changed during validation: " + name + ". Retry --check.")
    backup=Path(tempfile.mkdtemp(prefix="dkss-overview-surfaces-backup-"))
    for name, data in original.items():
        if data is not None:
            target=backup / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    result=apply(root, "--whitespace=nowarn")
    if result.returncode:
        raise RuntimeError("git apply stopped. Backup: " + str(backup) + "\n"
                           + result.stderr.decode("utf-8", "replace"))
    print("BACKUP:", backup)
    print("VEHICLE_OVERVIEW_SURFACES_OK")
    print("Stop Flask with Ctrl+C, then restart with the same command:")
    print("py -m flask --app app run --host=0.0.0.0 --port=5000")
    print("Open the vehicle Overview tab and press Ctrl+F5.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, SyntaxError, ValueError) as error:
        print("STOP:", error, file=sys.stderr)
        sys.exit(1)
