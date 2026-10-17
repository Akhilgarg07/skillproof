# Releasing

Releases are published by [`.github/workflows/release.yml`](.github/workflows/release.yml)
when you push a version tag. PyPI is reached through **Trusted Publishing**, so there
is no API token to create or store.

## One-time setup

1. **PyPI account:** create one at <https://pypi.org/account/register/> and turn on
   two-factor authentication (required to publish).
2. **Trusted publisher:** go to <https://pypi.org/manage/account/publishing/>, and
   under *Add a new pending publisher* → *GitHub* enter:

   | field | value |
   |---|---|
   | PyPI project name | `skillproof` |
   | Owner | `Akhilgarg07` |
   | Repository name | `skillproof` |
   | Workflow name | `release.yml` |
   | Environment name | `pypi` |

   A pending publisher doesn't reserve the name: publish soon after adding it.
3. **GitHub environment (optional but recommended):** in the repository go to
   *Settings → Environments → New environment*, name it `pypi`, and add yourself as a
   required reviewer. Every release then waits for your click before it uploads.

## Each release

```bash
# 1. set the version in src/skillproof/__init__.py, e.g. __version__ = "0.1.1"
# 2. commit and push to main, wait for CI to pass
git tag v0.1.1
git push origin v0.1.1
```

The workflow then:

1. checks that the tag matches `__version__`, builds the sdist and wheel, runs `twine check`;
2. uploads them to PyPI (`pip install skillproof` and `uvx skillproof` work a minute later);
3. creates a GitHub Release with auto-generated notes and moves the major tag (`v0`)
   to the new release, so `uses: akhilgarg07/skillproof@v0` gets the new action.

A version can be uploaded to PyPI only once. If something goes wrong after the upload,
fix it and release the next patch version.

## Check a build locally

```bash
python -m pip install build twine
python -m build && python -m twine check --strict dist/*
```
