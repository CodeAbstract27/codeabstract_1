"""
Module Allowlist for Import Abstraction

Phase 0 / D3 fix.

``ast.alias`` nodes were handled nowhere, so the whole import block passed
through to the LLM verbatim — leaking vendor names (``import stripe``) and
internal package paths (``from acme_internal.billing import ledger``).

Blanket-abstracting every import would cost a lot of utility: an LLM that
cannot see ``import asyncio`` or ``from typing import Optional`` loses most
of its ability to reason about the code. So imports are split in two:

* **Allowlisted** — the standard library plus widely-used public packages.
  These reveal nothing proprietary and are kept verbatim.
* **Everything else** — vendor SDKs and internal packages. These become
  ``MODULE_n`` tokens, consistent with their use sites.

Note that this is deliberately an *allowlist*, not a blocklist: an unknown
module is abstracted. Failing closed is the only safe default here, because
the internal package names are exactly the ones nobody thought to list.
"""

import sys
from typing import Set

# ═══════════════════════════════════════════════════════════
# Standard library
# ═══════════════════════════════════════════════════════════
# sys.stdlib_module_names is available from Python 3.10.  The project
# supports 3.9, so fall back to an explicit list of the modules that
# actually show up in application code.

_STDLIB_FALLBACK: Set[str] = {
    'abc', 'argparse', 'ast', 'asyncio', 'base64', 'binascii', 'bisect',
    'calendar', 'collections', 'concurrent', 'configparser', 'contextlib',
    'copy', 'csv', 'ctypes', 'dataclasses', 'datetime', 'decimal', 'difflib',
    'email', 'enum', 'errno', 'functools', 'gc', 'getpass', 'glob', 'gzip',
    'hashlib', 'heapq', 'hmac', 'html', 'http', 'importlib', 'inspect', 'io',
    'ipaddress', 'itertools', 'json', 'keyword', 'linecache', 'locale',
    'logging', 'math', 'mimetypes', 'multiprocessing', 'operator', 'os',
    'pathlib', 'pickle', 'platform', 'pprint', 'queue', 'random', 're',
    'secrets', 'select', 'shlex', 'shutil', 'signal', 'site', 'smtplib',
    'socket', 'sqlite3', 'ssl', 'stat', 'string', 'struct', 'subprocess',
    'sys', 'tarfile', 'tempfile', 'textwrap', 'threading',
    'time', 'timeit', 'token', 'tokenize', 'traceback', 'types', 'typing',
    'unicodedata', 'unittest', 'urllib', 'uuid', 'venv', 'warnings',
    'weakref', 'xml', 'zipfile', 'zlib',
}

_STDLIB: Set[str] = set(getattr(sys, 'stdlib_module_names', None) or _STDLIB_FALLBACK)

# ═══════════════════════════════════════════════════════════
# Widely-used public packages
# ═══════════════════════════════════════════════════════════
# Presence of these in an import block tells an observer nothing
# proprietary — they are the ambient vocabulary of Python development.

_PUBLIC_PACKAGES: Set[str] = {
    # Web frameworks and servers
    'flask', 'django', 'fastapi', 'starlette', 'tornado', 'bottle', 'sanic',
    'uvicorn', 'gunicorn', 'werkzeug', 'jinja2', 'aiohttp', 'httpx',

    # HTTP and networking
    'requests', 'urllib3', 'websockets', 'paramiko',

    # Data and scientific computing
    'numpy', 'np', 'pandas', 'pd', 'scipy', 'matplotlib', 'seaborn', 'plotly',
    'sklearn', 'statsmodels', 'polars', 'pyarrow', 'dask',

    # Machine learning
    'torch', 'tensorflow', 'keras', 'transformers', 'datasets', 'lightgbm',
    'xgboost', 'catboost', 'onnx', 'accelerate', 'peft',

    # Databases and ORMs
    'sqlalchemy', 'alembic', 'psycopg2', 'psycopg', 'pymongo', 'redis',
    'pymysql', 'asyncpg', 'peewee', 'motor', 'elasticsearch',

    # Validation, serialisation, config
    'pydantic', 'marshmallow', 'attr', 'attrs', 'cattrs', 'yaml', 'toml',
    'orjson', 'ujson', 'msgpack', 'dotenv', 'environs', 'dynaconf',

    # CLI and terminal
    'click', 'typer', 'rich', 'questionary', 'colorama', 'tqdm', 'tabulate',
    'prompt_toolkit', 'blessed',

    # Testing
    'pytest', 'unittest2', 'mock', 'hypothesis', 'faker', 'factory',
    'freezegun', 'responses', 'vcr', 'coverage',

    # Task queues and scheduling
    'celery', 'rq', 'apscheduler', 'schedule', 'dramatiq',

    # Crypto and auth
    'cryptography', 'nacl', 'jwt', 'jose', 'passlib', 'bcrypt', 'argon2',
    'authlib', 'oauthlib',

    # Cloud SDKs — the *SDK* is public knowledge; the credentials are not,
    # and those are handled by the value-level secret detector.
    'boto3', 'botocore', 'google', 'azure', 'kubernetes', 'docker',

    # Utilities
    'dateutil', 'pytz', 'arrow', 'pendulum', 'humanize', 'inflection',
    'more_itertools', 'toolz', 'cachetools', 'tenacity', 'retrying',
    'structlog', 'loguru', 'sentry_sdk', 'prometheus_client',
    'pillow', 'PIL', 'openpyxl', 'lxml', 'bs4', 'markdown', 'pygments',
    'setuptools', 'pkg_resources', 'pip', 'wheel',
}

SAFE_MODULES: Set[str] = _STDLIB | _PUBLIC_PACKAGES


def is_safe_module(module_path: str) -> bool:
    """
    True if *module_path* may be sent to the LLM verbatim.

    Only the root package is considered: ``os.path`` is safe because ``os``
    is, while ``acme_internal.billing`` is not, because ``acme_internal``
    is not on the list.

    Relative imports (``from . import x``) carry no name at all and are
    always safe.

    Args:
        module_path: Dotted module path, e.g. ``'os.path'`` or ``'stripe'``.

    Returns:
        True if the module is allowlisted.
    """
    if not module_path:
        # Relative import — ``from . import foo`` has module=None.
        return True

    root = module_path.split('.', 1)[0]
    return root in SAFE_MODULES


# ═══════════════════════════════════════════════════════════
# JavaScript / TypeScript
# ═══════════════════════════════════════════════════════════
# Phase 4.  The same argument as above, in another ecosystem: a bare
# ``import express from 'express'`` reveals nothing proprietary, whereas
# ``import { ledger } from '@acme/billing'`` names an internal package and
# an internal module in one line.  Unknown scopes and every relative path
# are abstracted, so this fails closed exactly as the Python list does.

_NODE_BUILTIN_MODULES: Set[str] = {
    'assert', 'buffer', 'child_process', 'cluster', 'console', 'crypto',
    'dgram', 'dns', 'events', 'fs', 'http', 'http2', 'https', 'net', 'os',
    'path', 'perf_hooks', 'process', 'querystring', 'readline', 'stream',
    'string_decoder', 'timers', 'tls', 'tty', 'url', 'util', 'v8', 'vm',
    'worker_threads', 'zlib',
}

_JS_PUBLIC_PACKAGES: Set[str] = {
    # Frameworks and runtimes
    'react', 'react-dom', 'react-native', 'next', 'vue', 'svelte', 'angular',
    'express', 'koa', 'fastify', 'hapi', 'nest', 'remix', 'nuxt', 'astro',
    'electron', 'gatsby',

    # Data, HTTP and state
    'axios', 'node-fetch', 'got', 'superagent', 'graphql', 'apollo-client',
    'redux', 'zustand', 'mobx', 'rxjs', 'swr', 'react-query',

    # Databases and ORMs
    'mongoose', 'sequelize', 'typeorm', 'prisma', 'knex', 'pg', 'mysql',
    'mysql2', 'sqlite3', 'redis', 'ioredis', 'mongodb',

    # Testing and tooling
    'jest', 'mocha', 'chai', 'sinon', 'vitest', 'cypress', 'playwright',
    'puppeteer', 'eslint', 'prettier', 'webpack', 'vite', 'rollup', 'babel',
    'typescript', 'ts-node', 'nodemon', 'esbuild',

    # Utilities
    'lodash', 'underscore', 'ramda', 'moment', 'dayjs', 'date-fns', 'uuid',
    'nanoid', 'chalk', 'commander', 'yargs', 'inquirer', 'dotenv', 'debug',
    'winston', 'pino', 'zod', 'yup', 'joi', 'classnames', 'immer',

    # Auth and crypto libraries, mirroring the Python list's 'jwt',
    # 'bcrypt', 'authlib' entries: these describe *how* a file authenticates,
    # not *who* it pays.
    'jsonwebtoken', 'bcrypt', 'bcryptjs', 'passport',

    # Generic cloud SDKs, mirroring Python's 'boto3', 'google', 'azure':
    # almost every deployed service touches one, so their presence
    # discriminates nothing.
    'aws-sdk', 'firebase', 'googleapis',
}

# Deliberately *not* allowlisted, in either language: the vendor SDKs whose
# presence is itself the business fact.  'import stripe' says the company
# takes card payments, 'twilio' that it sends SMS, 'openai' what it spends
# its inference budget on -- and the proposal names brand references as a
# protected category, with Stripe as its worked example.  The Python list
# has always excluded them; the JavaScript list did not, so the same import
# was hidden in one language and transmitted in the other.

SAFE_JS_MODULES: Set[str] = _NODE_BUILTIN_MODULES | _JS_PUBLIC_PACKAGES


def is_safe_js_module(module_path: str) -> bool:
    """
    True if a JavaScript/TypeScript module specifier may be sent verbatim.

    Relative and absolute paths (``./billing/ledger``, ``../lib``, ``/src``)
    are always treated as internal -- a path inside the user's project is
    proprietary by definition, and its segments often name the business
    domain more clearly than the code does.

    Scoped packages are judged on the whole scope-and-name (``@types/node``
    is public, ``@acme/billing`` is not, and ``@acme`` is what tells them
    apart). Subpaths are ignored: ``lodash/debounce`` is as public as
    ``lodash``.

    Args:
        module_path: Specifier as written in the import or require.

    Returns:
        True if the specifier is allowlisted.
    """
    if not module_path:
        return False

    specifier = module_path.strip()
    if specifier.startswith(('.', '/', '~')):
        return False

    if specifier.startswith('node:'):
        specifier = specifier[len('node:'):]

    if specifier.startswith('@'):
        parts = specifier.split('/')
        scope_and_name = '/'.join(parts[:2])
        return scope_and_name in SAFE_JS_MODULES or parts[0] in ('@types',)

    return specifier.split('/', 1)[0] in SAFE_JS_MODULES
