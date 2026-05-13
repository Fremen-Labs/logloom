from setuptools import setup, find_packages

setup(
    name="logloom",
    version="0.1.0",
    packages=find_packages(),
    install_requires=["structlog"],
    python_requires=">=3.8",
    description="Weave your codebase into every log line",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
)