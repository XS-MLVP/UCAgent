#!/usr/bin/env python3

from setuptools import setup, find_packages
import os
import importlib.util
from setuptools.command.install import install

# Read the contents of README.en.md
current_directory = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(current_directory, 'README.en.md'), encoding='utf-8') as f:
    long_description = f.read()

# Read requirements from requirements.txt
with open(os.path.join(current_directory, 'requirements.txt'), encoding='utf-8') as f:
    requirements = [line.strip() for line in f if line.strip() and not line.startswith('#')]


def version_info():
    spec = importlib.util.spec_from_file_location("version", os.path.join(current_directory, "vagent", "version.py"))
    version_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(version_module)
    return {
        "version": version_module.__version__,
        "author": version_module.__author__,
        "author_email": version_module.__email__,
        "description": version_module.__description__
    }


class PostInstallCommand(install):
    def run(self):
        install.run(self)
        default_user_cfg = os.path.join(os.path.expanduser("~"), '.ucagent/setting.yaml')
        if not os.path.exists(default_user_cfg):
            default_cfg = os.path.join(current_directory, 'vagent/setting.yaml')
            os.makedirs(os.path.dirname(default_user_cfg), exist_ok=True)
            with open(default_cfg, 'r', encoding='utf-8') as src, open(default_user_cfg, 'w', encoding='utf-8') as dst:
                dst.write(src.read())
            print(f"Default configuration file created at {default_user_cfg}")
        else:
            print(f"Configuration file already exists at {default_user_cfg}, skipping creation.")

setup(
    name="UCAgent",
    **version_info(),
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/XS-MLVP/UCAgent",
    project_urls={
        "Bug Reports": "https://github.com/XS-MLVP/UCAgent/issues",
        "Source": "https://github.com/XS-MLVP/UCAgent",
        "Documentation": "https://github.com/XS-MLVP/UCAgent#readme",
    },
    packages=find_packages(exclude=["tests*", "examples*", "output*"]),
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
            "lang/**/*",
        ],
    },
    zip_safe=False,
    keywords="hardware verification AI agent chip testing",
    cmdclass={
        'install': PostInstallCommand,
    },
)
