EbsAnalyzer

Installation:
    1. Install Python 2.7 if not already installed.
    2. Install boto3, botocore, and arrow.  Use "sudo pip install boto3 botocore arrow".

Quick Start:

$ python EbsCostAnalyzer.py -a [aws access key] -s [aws secret key]
$ python EbsCostAnalyzer.py -p [profile name]
$ AWS_DEFAULT_PROFILE=default python EbsCostAnalyzer.py

For more information about options:

$ python EbsCostAnalyzer.py -h
