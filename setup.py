# (C) 2025, 2026 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net>
# SPDX-License-Identifier: GPL-3.0-or-later

from setuptools import setup, find_packages
from pathlib import Path

here = Path(__file__).parent.resolve()

def read_long_description():
    for candidate in ("ABOUT.md", "PYPI_DESCRIPTION.md", "README.md"):
        path = here / candidate
        if path.exists():
            return path.read_text(encoding="utf-8"), "text/markdown"
    return "Patchvec — A lightweight, pluggable vector search microservice.", "text/plain"

long_description, long_type = read_long_description()

setup(
    name="patchvec",                       # external name
    version="0.5.6",
    description="Patchvec — A lightweight, pluggable vector search microservice.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Rodrigo Rodrigues da Silva",
    author_email="rodrigopitanga@posteo.net",
    license="GPL-3.0-or-later",
    python_requires=">=3.10,<3.15",
    packages=find_packages(include=["pave", "pave.*"]),  # internal package
    include_package_data=True,
    package_data={"pave.assets": ["*.png","*.html"]},
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
    extras_require={
        "cpu": [
            # torch CPU-only wheels from PyTorch index (Linux x86_64)
            "torch @ https://download.pytorch.org/whl/cpu/torch-2.10.0%2Bcpu-cp310-cp310-manylinux_2_28_x86_64.whl ; python_version>='3.10' and python_version<'3.11' and sys_platform=='linux' and platform_machine=='x86_64'",
            "torch @ https://download.pytorch.org/whl/cpu/torch-2.10.0%2Bcpu-cp311-cp311-manylinux_2_28_x86_64.whl ; python_version>='3.11' and python_version<'3.12' and sys_platform=='linux' and platform_machine=='x86_64'",
            "torch @ https://download.pytorch.org/whl/cpu/torch-2.10.0%2Bcpu-cp312-cp312-manylinux_2_28_x86_64.whl ; python_version>='3.12' and python_version<'3.13' and sys_platform=='linux' and platform_machine=='x86_64'",
            "torch @ https://download.pytorch.org/whl/cpu/torch-2.10.0%2Bcpu-cp313-cp313-manylinux_2_28_x86_64.whl ; python_version>='3.13' and python_version<'3.14' and sys_platform=='linux' and platform_machine=='x86_64'",
            "torch @ https://download.pytorch.org/whl/cpu/torch-2.10.0%2Bcpu-cp314-cp314-manylinux_2_28_x86_64.whl ; python_version>='3.14' and python_version<'3.15' and sys_platform=='linux' and platform_machine=='x86_64'",
            # torch CPU-only wheels (Windows x64)
            "torch @ https://download.pytorch.org/whl/cpu/torch-2.10.0%2Bcpu-cp310-cp310-win_amd64.whl ; python_version>='3.10' and python_version<'3.11' and sys_platform=='win32'",
            "torch @ https://download.pytorch.org/whl/cpu/torch-2.10.0%2Bcpu-cp311-cp311-win_amd64.whl ; python_version>='3.11' and python_version<'3.12' and sys_platform=='win32'",
            "torch @ https://download.pytorch.org/whl/cpu/torch-2.10.0%2Bcpu-cp312-cp312-win_amd64.whl ; python_version>='3.12' and python_version<'3.13' and sys_platform=='win32'",
            "torch @ https://download.pytorch.org/whl/cpu/torch-2.10.0%2Bcpu-cp313-cp313-win_amd64.whl ; python_version>='3.13' and python_version<'3.14' and sys_platform=='win32'",
            "torch @ https://download.pytorch.org/whl/cpu/torch-2.10.0%2Bcpu-cp314-cp314-win_amd64.whl ; python_version>='3.14' and python_version<'3.15' and sys_platform=='win32'",
            # torch for macOS (no CUDA on mac, PyPI wheels are CPU-only)
            "torch>=2.10.0 ; sys_platform=='darwin'",
            "faiss-cpu>=1.7.1",
        ],
        "gpu": [
            "faiss-gpu>=1.7.1",
        ],
    },
    entry_points={
        "console_scripts": [
            "pavesrv=pave.main:main_srv",
            "pavecli=pave.cli:main_cli",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Programming Language :: Python :: 3 :: Only",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Programming Language :: Python :: 3.14",
        "Framework :: FastAPI",
        "Topic :: Database",
        "Topic :: Internet :: WWW/HTTP :: HTTP Servers",
    ],
    project_urls={
        "Homepage": "https://gitlab.com/flowlexi/patchvec",
        "Source": "https://gitlab.com/flowlexi/patchvec",
        "Tracker": "https://gitlab.com/flowlexi/patchvec/issues",
    },
)
