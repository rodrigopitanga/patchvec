# (C) 2025 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net>
# SPDX-License-Identifier: GPL-3.0-or-later

from setuptools import setup, find_packages
from pathlib import Path

here = Path(__file__).parent.resolve()

def read_long_description():
    for candidate in ("ABOUT.md", "PYPI_DESCRIPTION.md", "README.md"):
        path = here / candidate
        if path.exists():
            return path.read_text(encoding="utf-8"), "text/markdown"
    return "PatchVec — A lightweight, pluggable vector search microservice.", "text/plain"

long_description, long_type = read_long_description()

setup(
    name="patchvec",                       # external name
    version="0.5.6dev0",
    description="PatchVec — A lightweight, pluggable vector search microservice.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Rodrigo Rodrigues da Silva",
    author_email="rodrigopitanga@posteo.net",
    license="GPL-3.0-or-later",
    python_requires=">=3.10",
    packages=find_packages(include=["pave", "pave.*"]),  # internal package
    include_package_data=True,
    install_requires=[
        "fastapi>=0.115.0",
        "uvicorn[standard]>=0.30.6",
        "txtai>=6.3.0",
        "pydantic>=2.8.2",
        "python-multipart>=0.0.9",
        "pypdf>=5.0.0",
        "pyyaml>=6.0.2",
        "python-dotenv>=1.0.1",
        "qdrant-client>=1.9.2",
        "sentence-transformers>=2.7.0",
        "openai>=1.0.0",
    ],
    entry_points={
        "console_scripts": [
            "pavesrv=pave.main:main_srv",
            "pavecli=pave.cli:main_cli",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)",
        "Programming Language :: Python :: 3 :: Only",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Framework :: FastAPI",
        "Topic :: Database",
        "Topic :: Internet :: WWW/HTTP :: HTTP Servers",
    ],
    project_urls={
        "Homepage": "https://gitlab.com/pitanga/patchvec",
        "Source": "https://gitlab.com/pitanga/patchvec",
        "Tracker": "https://gitlab.com/pitanga/patchvec/issues",
    },
)
