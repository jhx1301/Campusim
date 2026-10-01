"""CEMAS package installation."""

import os
import runpy

from setuptools import find_packages, setup


ROOT = os.path.abspath(os.path.dirname(__file__))

with open(os.path.join(ROOT, "requirements.txt"), encoding="utf-8") as handle:
    requirements = [line.strip() for line in handle if line.strip() and not line.startswith("#")]

version = runpy.run_path(os.path.join(ROOT, "cemas", "version.py"))["__version__"]

with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as handle:
    long_description = handle.read()

setup(
    name="cemas",
    version=version,
    author="CEMAS Authors",
    description="Campus Epidemic Multi-Agent Simulation with LLM-driven adaptive policy control",
    long_description=long_description,
    long_description_content_type="text/markdown",
    license="MIT",
    keywords=[
        "epidemic simulation", "agent-based model", "campus", "LLM",
        "adaptive interventions", "COVID-19",
    ],
    platforms=["OS Independent"],
    classifiers=[
        "Environment :: Console",
        "Intended Audience :: Science/Research",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Topic :: Scientific/Engineering",
    ],
    packages=find_packages(exclude=("tests", "tests.*", "examples", "examples.*")),
    package_data={"covasim": ["data/assets/*"]},
    include_package_data=True,
    python_requires=">=3.10",
    install_requires=requirements,
)
