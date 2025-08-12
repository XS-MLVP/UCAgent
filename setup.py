#!/usr/bin/env python3

from setuptools import setup, find_packages
import os

# Read the contents of README.md
current_directory = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(current_directory, 'README.md'), encoding='utf-8') as f:
    long_description = f.read()

# Read requirements from requirements.txt
with open(os.path.join(current_directory, 'requirements.txt'), encoding='utf-8') as f:
    requirements = [line.strip() for line in f if line.strip() and not line.startswith('#')]

setup(
    name="UCAgent",
    version="1.0.0",
    author="XS-MLVP",
    author_email="contact@xs-mlvp.org",
    description="UnityChip Verification Agent - AI-powered hardware verification tool",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/XS-MLVP/UCAgent",
    project_urls={
        "Bug Reports": "https://github.com/XS-MLVP/UCAgent/issues",
        "Source": "https://github.com/XS-MLVP/UCAgent",
        "Documentation": "https://github.com/XS-MLVP/UCAgent#readme",
    },
    packages=find_packages(exclude=["tests*", "examples*", "output*", "doc*"]),
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Testing",
        "Topic :: Scientific/Engineering :: Electronic Design Automation (EDA)",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.8",
    install_requires=requirements,
    entry_points={
        "console_scripts": [
            "ucagent=vagent.cli:main",
        ],
    },
    include_package_data=True,
    package_data={
        "vagent": [
            "config/*.yaml",
            "template/**/*",
        ],
    },
    zip_safe=False,
    keywords="hardware verification AI agent chip testing",
)
