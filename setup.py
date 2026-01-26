import pathlib

from setuptools import find_packages, setup

here = pathlib.Path(__file__).parent.resolve()
long_description = (here / "README.md").read_text(encoding="utf-8")

setup(
    name="sqsx",
    version="0.7.0",
    description="A simple task processor for Amazon SQS",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/allisson/pysqsx",
    author="Allisson Azevedo",
    author_email="allisson@gmail.com",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Programming Language :: Python :: 3.14",
    ],
    keywords="aws, sqs",
    packages=find_packages(),
    install_requires=["boto3>=1.33.13", "pydantic>=2.5.2"],
)
