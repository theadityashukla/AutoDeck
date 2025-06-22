#!/usr/bin/env python3
"""
Setup script for SuperGrobid
"""

from setuptools import setup, find_packages
from pathlib import Path

# Read the README file
this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text()

# Read requirements
requirements = []
with open("requirements.txt", "r") as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith("#"):
            requirements.append(line)

setup(
    name="supergrobid",
    version="1.0.0",
    author="SuperGrobid Team",
    author_email="team@supergrobid.com",
    description="A Hybrid, Python-Native Scientific Document Parser",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/your-org/supergrobid",
    packages=find_packages(),
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Science/Research",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
        "Topic :: Text Processing :: Markup",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
    python_requires=">=3.8",
    install_requires=requirements,
    extras_require={
        "dev": [
            "pytest>=7.4.0",
            "pytest-cov>=4.0.0",
            "black>=23.0.0",
            "flake8>=6.0.0",
            "mypy>=1.0.0",
        ],
        "full": [
            "nougat-ocr>=0.1.7",
            "layoutparser[ocr]>=0.3.4",
            "camelot-py[cv]>=0.11.0",
            "pdfx>=1.3.0",
            "im2latex>=0.1.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "supergrobid=cli:cli",
        ],
    },
    include_package_data=True,
    package_data={
        "supergrobid": ["*.yaml", "*.yml"],
    },
    keywords=[
        "pdf",
        "parser",
        "document",
        "scientific",
        "academic",
        "grobid",
        "nougat",
        "pymupdf",
        "layout",
        "ocr",
        "nlp",
        "ai",
        "machine-learning",
    ],
    project_urls={
        "Bug Reports": "https://github.com/your-org/supergrobid/issues",
        "Source": "https://github.com/your-org/supergrobid",
        "Documentation": "https://supergrobid.readthedocs.io/",
    },
) 