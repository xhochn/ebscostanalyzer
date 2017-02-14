#----------------------------------------------------------------------------
# Copyright 2017, FittedCloud, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
#Unless required by applicable law or agreed to in writing, software
#distributed under the License is distributed on an "AS IS" BASIS,
#WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#See the License for the specific language governing permissions and
#limitations under the License.
#
#Author: Gregory Fedynyshyn (greg@fittedcloud.com)
#----------------------------------------------------------------------------

import boto3
import botocore
import sys
import traceback
import os
import time
import pytz
import datetime
import arrow
import argparse
import json
from dateutil.tz import *
from collections import namedtuple

FC_AWS_ENV = "AWS_DEFAULT_PROFILE"
FC_TIME_ZONE = "US/Eastern"
TIME_FMT = 'YYYY-MM-DDTHH:mm:ssZ'
FC_EBS_STATUS_ATTACHED = 'attached'
FC_EBS_STATUS_UNATTACHED = 'unattached'
FC_STAT_DAYS = 14
FC_STAT_PERIOD = 86400 # one day in seconds
GP2_IOPS_PER_GB = 3
IO1_IOPS_THRESHOLD = 0.75

# Iops is max avilable Iops.
# To get actual IOPS, use the sum of ReadIops and WriteIops.
EbsInfo = namedtuple("EbsInfo", "VolId VolName Ec2Id Ec2Name Type Size Device AvailabilityZone Iops UsedSize ReadIops WriteIops CreateTime CurrTime State Status DeleteOnTermination Encrypted KmsKeyId FcVol Tags")

# We dynamically update regions in our software, but for the
# purposes of this script, hardcoding is fine.
aws_regions = [
    'us-east-1',       # US East (N. Virginia)
    'us-west-2',       # US West (Oregon)
    'us-west-1',       # US West (N. California)
    'eu-west-1',       # EU (Ireland)
    'eu-central-1',    # EU (Frankfurt)
    'ap-southeast-1',  # Asia Pacific (Singapore)
    'ap-northeast-1',  # Asia Pacific (Tokyo)
    'ap-southeast-2',  # Asia Pacific (Sydney)
    'ap-northeast-2',  # Asia Pacific (Seoul)
    'sa-east-1',       # South America (Sao Paulo)
    'us-east-2',       # US East (Ohio)
    'ap-south-1',      # Asia Pacific (Mumbai)
    'ca-central-1',    # Canada (Central)
    'eu-west-2',       # EU (London)
]

# We dynamically update rates in our software, but for the
# purposes of this script, hardcoding is fine.
ebs_monthly_rates={
    "io1": {
        "ap-south-1": 0.131,
        "us-east-1": 0.125,
        "ap-northeast-1": 0.142,
        "sa-east-1": 0.238,
        "ap-northeast-2": 0.1278,
        "ap-southeast-1": 0.138,
        "ca-central-1": 0.138,
        "ap-southeast-2": 0.138,
        "us-west-2": 0.125,
        "us-east-2": 0.125,
        "us-west-1": 0.138,
        "eu-central-1": 0.149,
        "eu-west-1": 0.138,
        "eu-west-2": 0.145
    },
    "standard": {
        "us-west-1": 0.08,
        "eu-west-1": 0.055,
        "us-east-1": 0.05,
        "ap-northeast-1": 0.08,
        "sa-east-1": 0.12,
        "ap-northeast-2": 0.08,
        "ap-southeast-1": 0.08,
        "ca-central-1": 0.055,
        "ap-southeast-2": 0.08,
        "us-west-2": 0.05,
        "ap-south-1": 0.08,
        "eu-central-1": 0.059,
        "us-east-2": 0.05,
        "eu-west-2": 0.058},
    "iops": {
        "ap-south-1": 0.068,
        "eu-west-1": 0.072,
        "us-east-1": 0.065,
        "us-east-2": 0.065,
        "sa-east-1": 0.091,
        "ap-northeast-2": 0.0666,
        "ap-southeast-1": 0.072,
        "ca-central-1": 0.072,
        "ap-southeast-2": 0.072,
        "us-west-2": 0.065,
        "us-west-1": 0.072,
        "eu-central-1": 0.078,
        "ap-northeast-1": 0.074,
        "eu-west-2": 0.076
    },
    "st1": {
        "us-east-1": 0.045,
        "us-west-1": 0.054,
        "ap-northeast-2": 0.051,
        "ap-northeast-1": 0.054,
        "eu-west-1": 0.05,
        "sa-east-1": 0.086,
        "ap-southeast-1": 0.054,
        "ca-central-1": 0.05,
        "ap-southeast-2": 0.054,
        "us-west-2": 0.045,
        "ap-south-1": 0.051,
        "eu-central-1": 0.054,
        "us-east-2": 0.045,
        "eu-west-2": 0.053
    },
    "sc1": {
        "us-east-1": 0.025,
        "ap-south-1": 0.029,
        "ap-northeast-2": 0.029,
        "us-east-2": 0.025,
        "ap-northeast-1": 0.03,
        "sa-east-1": 0.048,
        "ap-southeast-1": 0.03,
        "ca-central-1": 0.028,
        "ap-southeast-2": 0.03,
        "us-west-2": 0.025,
        "us-west-1": 0.03,
        "eu-central-1": 0.03,
        "eu-west-1": 0.028,
        "eu-west-2": 0.029
    },
    "gp2": {
        "us-east-1": 0.1,
        "us-west-1": 0.12,
        "ap-northeast-2": 0.114,
        "us-east-2": 0.1,
        "ap-northeast-1": 0.12,
        "eu-west-1": 0.11,
        "ap-southeast-1": 0.12,
        "ca-central-1": 0.11,
        "ap-southeast-2": 0.12,
        "us-west-2": 0.1,
        "ap-south-1": 0.114,
        "eu-central-1": 0.119,
        "sa-east-1": 0.19,
        "eu-west-2": 0.116
    }
}

#
# Simple roundup function
#
def roundup(a):
    return a if (int(a) == a) else a + 1

#
# Find maximum value in a list of datapoints returned
# from a call to get_metric_statistics
#
def find_max(data, field):
    m = 0
    for i in range(len(data)):
        m = max(m, data[i][field])
    return m

#
# returns maximum value for IOPS over 14-day period by default.
# metricName can be 'VolumeReadOps' or 'VolumeWriteOps'
#
def get_iops(cloudWatch, ebsId, metricName, createTime, useAvg):
    iops = 0
    startTime = arrow.now(FC_TIME_ZONE).replace(days=-FC_STAT_DAYS, hour=0, minute=0, second=0, microsecond=0).format(TIME_FMT)
    endTime = arrow.now(FC_TIME_ZONE).format(TIME_FMT)

    if ((arrow.get(startTime) - arrow.get(createTime)).days <= FC_STAT_DAYS):
        return -1 # Younger than 14 days

    if (useAvg == False):
        statistic = 'Maximum'
    else:
        statistic = 'Average'
    try:
        response = cloudWatch.get_metric_statistics(Namespace='AWS/EBS',
                                            MetricName=metricName,
                                            Dimensions=[{'Name': 'VolumeId',
                                                         'Value': ebsId}],
                                            StartTime=startTime,
                                            EndTime=endTime,
                                            Period=FC_STAT_PERIOD,
                                            Statistics=[statistic],
                                            Unit='Count')
        # because we starting from beginning of day, we will usually
        # have FC_STAT_DAYS + 1 data points
        # CloudWatch will occasionally have bizarre values for IOPS.
        # I don't know why, but I sometimes see up to 300,000+ IOPS for an
        # 8GB gp2 volume.  I currently have a support ticket open for this.
        if (len(response['Datapoints']) == 0):
            iops = -1 # sometimes cloudwatch doesn't save data, no idea why
        elif (useAvg == False):
            iops = find_max(response['Datapoints'], 'Maximum')
        else:
            iops = find_max(response['Datapoints'], 'Average')
    except:
        e = sys.exc_info()
        print("Failed to get volume statistics: %s" %(str(e)))
        iops = -2
    return iops

#
# Queries volumes and puts results into list of EbsInfo structs
# Requires ec2Connection to describe_volumes and cloudWatch to
# query statistics
#
def get_ebs_info(ec2Connection, cloudWatch, ebsIdList, useAvg):
        listOfEbsInfo = [] 
        ebsInfo = None 
        count = 0
        retry = 5
        while count < retry:
            count += 1 
            try:
                responseVol = ec2Connection.describe_volumes(DryRun=False, VolumeIds=ebsIdList)
                for volume in responseVol['Volumes']:
                    # Skip root devices.
                    # Paravirtual reserves /dev/sda1 for root dev
                    # HVM could be either /dev/sda1 or /dev/xvda
                    if (('Attachments' in volume or volume['Attachments']) and
                        (len(volume['Attachments']) > 0)):
                        if (volume['Attachments'][0]['Device'] == "/dev/sda1" or
                            volume['Attachments'][0]['Device'] == "/dev/xvda"):
                            continue

                    # get EBS tags
                    volTags = ec2Connection.describe_tags(
                        Filters=[{'Name': 'resource-id', 'Values': [volume['VolumeId']]}])
                    utcStr = arrow.now(FC_TIME_ZONE).format(TIME_FMT)
                    iops = volume['Iops'] if 'Iops' in volume else 0
                    kmsKeyId = volume['KmsKeyId'] if 'KmsKeyId' in volume else '0'
                    if cloudWatch:
                        readIops = get_iops(cloudWatch, volume['VolumeId'], 'VolumeReadOps', arrow.get(volume['CreateTime']).to(FC_TIME_ZONE).format(TIME_FMT), useAvg)
                        writeIops = get_iops(cloudWatch, volume['VolumeId'], 'VolumeWriteOps', arrow.get(volume['CreateTime']).to(FC_TIME_ZONE).format(TIME_FMT), useAvg)

                    # skip vol on an error
                    if (readIops == -2 or writeIops == -2):
                        continue

                    # get volume name if it has one
                    volName = ""
                    for tag in volTags['Tags']:
                        if tag['Key'] == 'Name' and tag['Value']:
                            volName = tag['Value']
                            break

                    if (not 'Attachments' in volume or
                        not volume['Attachments'] or
                        len(volume['Attachments']) == 0):
                        ebsInfo = EbsInfo(
                            VolId       = volume['VolumeId'],
                            VolName     = volName,
                            Ec2Id       = "NA",
                            Ec2Name     = "",
                            Type        = volume['VolumeType'],
                            Size        = volume['Size'],
                            Device      = "NA",
                            AvailabilityZone = volume['AvailabilityZone'],
                            Iops        = iops,
                            UsedSize    = volume['Size'],
                            ReadIops    = readIops,
                            WriteIops   = writeIops,
                            CreateTime  = arrow.get(volume['CreateTime']).to(FC_TIME_ZONE).format(TIME_FMT),
                            State       = volume['State'],
                            Status      = FC_EBS_STATUS_UNATTACHED,
                            DeleteOnTermination = "NA",
                            CurrTime    = utcStr,
                            FcVol       = "NA",
                            Encrypted   = volume['Encrypted'],
                            KmsKeyId    = kmsKeyId,
                            Tags        = volTags['Tags'])
                    else:
                        # get ec2 instance name if it has one
                        ec2Tags = ec2Connection.describe_tags(         \
                            Filters=[{'Name': 'resource-id', 'Values': \
                                    [volume['Attachments'][0]['InstanceId']]}])

                        ec2Name = ""
                        for tag in ec2Tags['Tags']:
                            if tag['Key'] == 'Name' and tag['Value']:
                                ec2Name = tag['Value']
                                break

                        ebsInfo = EbsInfo(
                            VolId       = volume['VolumeId'],
                            VolName     = volName,
                            Ec2Id       = volume['Attachments'][0]['InstanceId'],
                            Ec2Name     = ec2Name,
                            Type        = volume['VolumeType'],
                            Size        = volume['Size'],
                            Device      = volume['Attachments'][0]['Device'],
                            AvailabilityZone = volume['AvailabilityZone'],
                            Iops        = iops,
                            UsedSize    = volume['Size'],
                            ReadIops    = readIops,
                            WriteIops   = writeIops,
                            CreateTime  = arrow.get(volume['CreateTime']).to(FC_TIME_ZONE).format(TIME_FMT),
                            State       = volume['State'],
                            Status      = FC_EBS_STATUS_ATTACHED,
                            DeleteOnTermination = volume['Attachments'][0]['DeleteOnTermination'],
                            CurrTime    = utcStr,
                            FcVol       = volume['Attachments'][0]['Device'],
                            Encrypted   = volume['Encrypted'],
                            KmsKeyId    = kmsKeyId,
                            Tags        = volTags['Tags'])
                    listOfEbsInfo.append(ebsInfo)
                break
            except botocore.exceptions.ClientError as e:
                print("Failed to get ebs volume info, ebsId={0}, %s".format(ebsIdList) %(e.response['Error']['Message']))
                if e.response['Error']['Code'] == 'Client.RequestLimitExceeded':
                    print("retry describe_volumes")
                    time.sleep(24*count)
                    continue
                return listOfEbsInfo
            except:
                e = sys.exc_info()
                print("Failed to get ebs volume info: %s" %(str(e)))
                traceback.print_exc()
                return listOfEbsInfo
        if count >= retry:
            print("Failed to get ebs volume info after retry")
        return listOfEbsInfo

#
# Pass EbsInfo struct as vol and return minimum available size in GB
# Currently, only supports gp2, st1, sc1, and io1.
#
def get_minimum_size(volType):
    if (volType == 'gp2' or volType == 'standard'):
        return 1
    if (volType == 'st1'):
        return 500
    if (volType == 'sc1'):
        return 500
    if (volType == 'io1'):
        return 4

    print("ERROR: invalid volume type")
    return -1

#
# Pass EbsInfo struct as vol and return maximum available size in GB
# Currently, only supports gp2, st1, sc1, and io1.  Turns out they are all 16TB
#
def get_maximum_size(volType):
    if (volType == 'gp2'):
        return 16*1024
    if (volType == 'st1'):
        return 16*1024
    if (volType == 'sc1'):
        return 16*1024
    if (volType == 'io1'):
        return 16*1024
    if (volType == 'standard'):
        return 1024

    print("ERROR: invalid volume type")
    return -1

#
# Return minimum possible IOPS based on volume type.
#
def get_minimum_iops(volType, size=0):
    if (volType == 'gp2'):
        return 100
    if (volType == 'st1'):
        return 500
    if (volType == 'sc1'):
        return 250
    if (volType == 'io1'):
        return 100
    if (volType == 'standard'):
        return 200

    print("ERROR: invalid volume type: %s" %(volType))
    return -1

#
# Return maximum possible IOPS based on volume type.
#
def get_maximum_iops(volType, size=0):
    if (volType == 'gp2'):
        return 10000
    if (volType == 'st1'):
        return 500
    if (volType == 'sc1'):
        return 250
    if (volType == 'io1'):
        return 20000
    if (volType == 'standard'):
        return 200

    print("ERROR: invalid volume type: %s" %(volType))
    return -1

#
# Return maximum available IOPS based on volume type and size
# 'size' parameter only matters for gp2
#
def get_available_iops(volType, size=0):
    if (volType == 'gp2'):
        iops = size * GP2_IOPS_PER_GB
        if (iops < get_minimum_iops('gp2')):
            return get_minimum_iops('gp2')
        elif (iops > get_maximum_iops('gp2')):
            return get_maximum_iops('gp2')
        else:
            return iops
    if (volType == 'st1'):
        return 500
    if (volType == 'sc1'):
        return 250
    if (volType == 'io1'):
        return 20000
    if (volType == 'standard'):
        return 200
        
    print("ERROR: invalid volume type: %s" %(volType))
    return -1

#
# Return monthly rates based on volume type, size, region
# and provisioned IOPS for io1
#
def get_monthly_rate(region, volType, volSize, volIops=0):
    if (volType not in ['gp2', 'standard', 'sc1', 'st1', 'io1']):
        print("ERROR: invalid volume type: %s" %(volType))
        return -1

    cost = ebs_monthly_rates[volType][region] * volSize
    if (volType == 'io1'):
        cost += ebs_monthly_rates['iops'][region] * volIops

    return cost

#
# Calculate cost savings of migration from old to new type, size, iops
# returns savings per month
#
def get_cost_savings(region, oldType, oldSize, oldIops,
                     newType, newSize, newIops):
    oldCost = get_monthly_rate(region, oldType, oldSize, oldIops)
    newCost = get_monthly_rate(region, newType, newSize, newIops)
    return oldCost - newCost

#
# Dump advisory info in json format.  Includes more fields than regular format.
#
def dump_advisory_json(advInfo):
    print json.dumps(advInfo, sort_keys=True, indent=4)

# We can use FittedCloud's EBS capacity rightsizing to ynamically resize a
# volume to be only as big as the amount of space being used.  On average,
# aws users overprovision by a factor of 2, so assume that for
# cost saving estimates.
#
# This function is called in two circumstance:
#   1. No migration advisories are found for the volume
#       - must be done after we check for advisories
#   2. The volume is either too young or has no cloudwatch data
#       - must be done before we check for advisories
# iops parameter only matters for io1
#
# returns cost savings
def capacity_rightsizing(region, volType, volSize, iops):
    newSize = max(volSize/2, get_minimum_size(volType))
    if (volType == 'io1'):
        oldIops = iops
        newIops = iops
    else:
        oldIops = get_available_iops(volType, volSize)
        newIops = get_available_iops(volType, newSize)

    cost = get_cost_savings(region,
                            volType,
                            volSize,
                            oldIops,
                            volType,
                            newSize,
                            newIops)
    return cost

#
# Loops through region list and finds volumes that can benefit from migration.
#
def analyze_ebs_motion(access, secret, rList, useAvg, useJson):
    # json lists for advisories
    json_advisory = {"Migration": [], "Unattached": []}

    # dictionary for tracking number and size of volumes analyzed
    summary = {'gp2': {'count': 0, 'size': 0},
               'st1': {'count': 0, 'size': 0},
               'sc1': {'count': 0, 'size': 0},
               'io1': {'count': 0, 'size': 0},
               'standard': {'count': 0, 'size': 0},
               'total_capacity': 0,
               'num_advisories': 0,
               'ebsmotion_savings': 0,
               'unattached_savings': 0,
               'capacity_savings': 0,
               'total_savings': 0}

    # loop through region list
    for r in rList:
        advisory_found = 0
        try:
            botoSession = boto3.Session(aws_access_key_id=access, aws_secret_access_key=secret, region_name=r)
            botoClient = boto3.client('ec2', aws_access_key_id=access, aws_secret_access_key=secret, region_name=r)
            cloudWatch = boto3.client('cloudwatch', aws_access_key_id=access, aws_secret_access_key=secret, region_name=r)
        except botocore.exceptions.ClientError as e:
            eMsg = e.response['Error']['Message']
            print("ERROR: Failed to get boto3.Session error = %s" %(eMsg))
            return
        except:
            e = sys.exc_info()
            print("ERROR: Failed to get boto3.Session region = %s error = %s" %(r, str(e)))
            traceback.print_exc()
            return

        ec2resource = botoSession.resource('ec2')

        ebsList = ec2resource.volumes.all()

        # fetch all volume information for region in one call
        volList = []
        for ebs in ebsList:
            volList.append(ebs.id)
        ebs_info = get_ebs_info(botoClient, cloudWatch, volList, useAvg)

        for vol in ebs_info:
            # update counters
            summary[vol.Type]['count'] += 1
            summary[vol.Type]['size'] += vol.Size
            summary['total_capacity'] += vol.Size

            # for some reason, cloudwatch will return 0 for Iops
            # for some volume types
            if (vol.Iops == 0):
                vol = vol._replace(Iops=get_available_iops(vol.Type, vol.Size))

            # convert to dictionary
            advInfo = vol._asdict()

            # - RecommendedType will be changed if migrating to new type
            # - RecommendedIops will be changed if io1 migrates to io1
            # with fewer provisioned IOPS
            # - RecommendedSize will be changed if io1 -> gp2, but gp2
            # must be increased in size to meet IOPS demand
            advInfo['RecommendedType'] = advInfo['Type']
            advInfo['RecommendedIops'] = advInfo['Iops']
            advInfo['RecommendedSize'] = advInfo['Size']
            advInfo['Region'] = r;
            if (useAvg == False):
                advInfo['MetricType'] = "max"
            else:
                advInfo['MetricType'] = "avg"

            totalIops = vol.ReadIops + vol.WriteIops

            # for unattached ebs, estimate cost savings by assuming
            # deletion of volume, as we cannot predict snapshot size
            if (vol.Status == FC_EBS_STATUS_UNATTACHED):
                advInfo['RecommendedSize'] = 0
                advInfo['RecommendedIops'] = 0

                # unattached and either too young or no cloudwatch data
                if (totalIops < 0):
                    totalIops = 0

            # if volume too young or no cloudwatch data, do ebs rightsizing
            elif (vol.ReadIops == -1 or vol.WriteIops == -1):
                cost = capacity_rightsizing(r, advInfo['Type'], advInfo['Size'], vol.Iops)
                totalIops = 0 # set to zero to avoid confusing output
                summary['capacity_savings'] += cost
                summary['total_savings'] += cost

            # Migration of GP2
            elif (vol.Type == 'gp2'):
                # There may be cases where we can save money by
                # migrating a gp2 less than 500GB to st1 or sc1
                # but using a simple heuristic for now.
                if (vol.Size >= get_minimum_size('st1')):
                    if (totalIops < get_available_iops('st1')):
                        advInfo['RecommendedType'] = 'st1'
                        advInfo['RecommendedIops'] = get_available_iops('sc1')
                if (vol.Size >= get_minimum_size('sc1')):
                    if (totalIops < get_available_iops('sc1')):
                        advInfo['RecommendedType'] = 'sc1'
                        advInfo['RecommendedIops'] = get_available_iops('sc1')

            # Migration of ST1
            elif (vol.Type == 'st1'):
                if (totalIops < get_available_iops('sc1')):
                    advInfo['RecommendedType'] = 'sc1'
                    advInfo['RecommendedIops'] = get_available_iops('sc1')

            # Migration of IO1
            elif (vol.Type == 'io1'):
                if (totalIops < get_maximum_iops('gp2')):
                    if (totalIops >= vol.Iops * IO1_IOPS_THRESHOLD):
                        advInfo['RecommendedType'] = 'gp2'

                        # Might need to increase size of gp2 to get same
                        # IOPS as io1's provisioned IOPS
                        if (vol.Size * GP2_IOPS_PER_GB < totalIops):
                            advInfo['RecommendedSize'] = roundup(totalIops / GP2_IOPS_PER_GB)
                            advInfo['RecommendedIops'] = advInfo['RecommendedSize'] * GP2_IOPS_PER_GB
                    else:
                        advInfo['RecommendedIops'] = max(totalIops, get_minimum_iops('io1'))

            # Migration of magnetic
            elif (vol.Type == 'standard'):
                # SC1 is roughly half the price per GB than magnetic, but
                # has a minimum size of 500GB.  It's possible in some
                # regions that migrating a 250GB magnetic to 500GB SC1
                # will cost more.  Using simple heuristic for size checking.
                if ((vol.Size >= get_minimum_size('sc1')) and
                    (vol.Size < get_maximum_size('sc1'))):
                    advInfo['RecommendedType'] = 'sc1'

            # calculate cost savings and advice string for an advisory
            if (advInfo['Type'] != advInfo['RecommendedType'] or
                advInfo['Iops'] != advInfo['RecommendedIops'] or
                advInfo['Size'] != advInfo['RecommendedSize'] or
                advInfo['Status'] == FC_EBS_STATUS_UNATTACHED):

                # only needed for commented-out message below
                advisory_found = 1

                # update counter
                summary['num_advisories'] += 1
                cost = get_cost_savings(r,
                                        advInfo['Type'],
                                        advInfo['Size'],
                                        advInfo['Iops'],
                                        advInfo['RecommendedType'],
                                        advInfo['RecommendedSize'],
                                        advInfo['RecommendedIops'])
                # round to two decimal places
                cost = round(cost, 2)

                # record total and per-advisory cost savings
                # per-advisory savings will be displayed in JSON output
                advInfo['MonthlyCostSavings'] = cost
                summary['total_savings'] += cost

                if (advInfo['Status'] == FC_EBS_STATUS_UNATTACHED):
                    advInfo['Advice'] = "Delete or take snapshot then delete."
                    summary['unattached_savings'] += cost
                    if (useJson == True):
                        json_advisory['Unattached'].append(advInfo)

                else:
                    # update cost savings for migration
                    summary['ebsmotion_savings'] += cost

                    advInfo['Advice'] = "Migrate to %s." %(advInfo['RecommendedType'])

                    if (advInfo['Size'] != advInfo['RecommendedSize']):
                        advInfo['Advice'] += "  Set size to %dGB." %(advInfo['RecommendedSize'])
                    # io1 -> io1 with fewer provisioned IOPS
                    elif (advInfo['Iops'] != advInfo['RecommendedSize'] and
                          advInfo['Type'] == advInfo['RecommendedType']):
                        advInfo['Advice'] += "  Set Iops to %d IOPS." %(advInfo['RecommendedIops'])
                    if (useJson == True):
                        json_advisory['Migration'].append(advInfo)

                # Finally, dump the output if there is an advisory
                if (useJson == False):
                    if (advInfo['VolName'] != ""):
                        vName = " (%s)" %(advInfo['VolName'])
                    else:
                        vName = ""

                    if (advInfo['Ec2Name'] != ""):
                        eName = " (%s)" %(advInfo['Ec2Name'])
                    else:
                        eName = ""
                    print(
                        "EBS Advisory:\n"
                        "\tRegion: %s\n"
                        "\tEC2 ID: %s%s\n"
                        "\tVolume ID: %s%s\n"
                        "\tCreate Time: %s\n"
                        "\tStatus: %s\n"
                        "\tType: %s\n"
                        "\tSize: %d GB\n"
                        "\tCurrent available IOPS: %d\n"
                        "\tOver a %d day period, %s IOPS observed %d\n"
                        "\tAdvice: %s\n"
                        "\tMonthly Cost Savings: $%.2f\n"
                        %(advInfo['Region'],
                        advInfo['Ec2Id'],
                        eName,
                        advInfo["VolId"],
                        vName,
                        advInfo['CreateTime'],
                        advInfo['Status'],
                        advInfo['Type'],
                        advInfo['Size'],
                        get_available_iops(advInfo['Type'], advInfo['Size']),
                        FC_STAT_DAYS,
                        advInfo['MetricType'],
                        totalIops,
                        advInfo['Advice'],
                        advInfo['MonthlyCostSavings']))

            # If no advisories, we can use FittedCloud's EBS rightsizing
            else:
                cost = capacity_rightsizing(r, advInfo['Type'], advInfo['Size'], vol.Iops)
                summary['capacity_savings'] += cost
                summary['total_savings'] += cost

        # No advisories found for this region.
        # Uncomment if you want to print out a message.
        #if (advisory_found == 0):
        #    print("No advisories for Region=%s" %(r))

    # Print a summary if not using JSON output
    if (useJson == False):
        total_capacity = 0
        for k in summary.keys():
            if (type(summary[k]) == type({})):
                vols = "{:,}".format(summary[k]['count'])
                size = "{:,}".format(summary[k]['size'])
                print("Number of %s volumes analyzed: %s (Total Capacity: %s GB)"
                      %(k, vols, size))

        print("Total EBS Capacity: {:,} GB".format(summary['total_capacity']))
        print("Total Advisories: {:,}".format(summary['num_advisories']))

        # some formatting magic to line up dollar signs with the largest value
        ebsmotion = "{:,.2f}".format(summary['ebsmotion_savings'])
        unattached = "{:,.2f}".format(summary['unattached_savings'])
        capacity = "{:,.2f}".format(summary['capacity_savings'])
        total = "{:,.2f}".format(summary['total_savings'])
        width = len(total)
        print("Estimated Monthly Cost Savings:")
        print("\tMigration/Type Switching:            ${0:{width}}{1}" \
              .format("", ebsmotion, width=(width+1)-len(ebsmotion)))
        print("\tUnattached EBS:                      ${0:{width}}{1}" \
              .format("", unattached, width=(width+1)-len(unattached)))
        print("\tCapacity Rightsizing (up to 50%):    ${0:{width}}{1}" \
              .format("", capacity, width=(width+1)-len(capacity)))
        print("\tTotal Savings:                       ${0:{width}}{1}" \
              .format("", total, width=(width+1)-len(total)))
    else:
        dump_advisory_json({'Advisories': json_advisory})
        dump_advisory_json({'Summary': summary})


def print_usage():
     print("EbsCostAdvisor.py <options>\n"
           "\tOptions are:\n\n"
           "\t-h --help - Display this help message\n"
           "\t-p --profile <profile name> - AWS profile name (can be used instead of -a and -s options)\n"
           "\t-a --accesskey <access key> - AWS access key\n"
           "\t-s --secretkey <secret key> - AWS secret key\n"
           "\t-r --regions <region1,region2,...> - A list of AWS regions.  If this option is omitted, all regions will be checked.\n"
           "\t-m --mean - Use average (mean) values instead of maximum values for metrics used to determine advisories.\n"
           "\t-j --json - Output in JSON format.\n\n"
           "\tOne of the following three parameters are required:\n"
           "\t\t1. Both the -a and -s options.\n"
           "\t\t2. The -p option.\n"
           "\t\t3. A valid " + FC_AWS_ENV + " enviornment variable.\n\n"
           "\tDepending on the number of EBS volumes being analyzed, this tool make take several minutes to run.")

def parse_options(argv):
    parser = argparse.ArgumentParser(prog="EbsCostAdvisor.py",
             add_help=False) # use print_usage() instead

    parser.add_argument("-p", "--profile", type=str, required=False)
    parser.add_argument("-a", "--access-key", type=str, required=False)
    parser.add_argument("-s", "--secret-key", type=str, required=False)
    parser.add_argument("-r", "--regions", type=str, default="")
    parser.add_argument("-m", "--mean", action="store_true", default=False)
    parser.add_argument("-j", "--json", action="store_true", default=False)

    args = parser.parse_args(argv)
    if (len(args.regions) == 0):
        return args.profile, args.access_key, args.secret_key, [], args.mean, args.json
    else:
        return args.profile, args.access_key, args.secret_key, args.regions.split(','), args.mean, args.json

def parse_args(argv):
    # ArgumentParser's built-in way of automatically handling -h and --help
    # leaves much to be desired, so using this hack instead.
    for arg in argv:
        if (arg == '-h' or arg == '--help'):
            print_usage()
            os._exit(0)

    p, a, s, rList, m, j = parse_options(argv[1:])

    return p, a, s, rList, m, j

if __name__ == "__main__":
    p, a, s, rList, m, j = parse_args(sys.argv)

    # need either -a and -s, -p, or AWS_DEFAULT_PROFILE environment variable
    if not a and not s and not p:
        if (FC_AWS_ENV in os.environ):
            p = os.environ[FC_AWS_ENV]
        else:
            print_usage()
            print("\nError: must provide either -p option or -a and -s options")
            os._exit(1)

    if a and not s and not p:
        print_usage()
        print("\nError: must provide secret access key using -s option")
        os._exit(1)

    if not a and s and not p:
        print_usage()
        print("\nError: must provide access key using -a option")
        os._exit(1)

    if p:
        try:
            home = os.environ["HOME"]
            pFile = open(home + "/.aws/credentials", "r")
            line = pFile.readline()
            p = "["+p+"]"
            while p not in line:
                line = pFile.readline()
                if (line == ""): # end of file
                    print_usage()
                    print("\nError: invalid profile: %s" %p)
                    os._exit(1)

            # get secret access key
            a = pFile.readline().strip().split(" ")[2]
            s = pFile.readline().strip().split(" ")[2]

        except:
            print("Error reading credentials for profile %s." %p)
            os._exit(1)

    if (len(rList) == 0):
        rList = aws_regions
    analyze_ebs_motion(a, s, rList, m, j)
