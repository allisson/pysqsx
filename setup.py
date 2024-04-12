import pathlib

from setuptools import find_packages, setup

here = pathlib.Path(__file__).parent.resolve()
long_description = (here / "README.md").read_text(encoding="utf-8")

setup(
    name="sqsx",
    version="0.5.0",
    description="A simple task processor for Amazon SQS",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/allisson/pysqsx",
    author="Allisson Azevedo",
    author_email="allisson@gmail.com",
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
    keywords="aws, sqs",
    packages=find_packages(),
    install_requires=["boto3>=1.33.13", "pydantic>=2.5.2"],
    tests_require=["pytest>=7.4.3", "pytest-cov>=4.1.0", "pre-commit==3.5.0"],
)
