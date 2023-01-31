"""
This script executed by a Glue job. The job take the access record data from S3 and process it.
 Processed data stored in S3 in a parquet file partitioned by timestamp of record as  year / month / day.
"""

import sys
import datetime
import re
from awsglue.transforms import *
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext
from awsglue.context import GlueContext
from awsglue.job import Job
from awsglue.dynamicframe import DynamicFrame

WEB_CLIENT = "Synapse-Web-Client"
SYNAPSER_CLIENT = "synapser"
R_CLIENT = "synapseRClient"
PYTHON_CLIENT = "synapseclient"
OLD_JAVA_CLIENT = "Synpase-Java-Client"
JAVA_CLIENT = "Synapse-Java-Client"
COMMAND_LINE_CLIENT = "synapsecommandlineclient"
ELB_CLIENT = "ELB-HealthChecker"
STACK_CLIENT = "SynapseRepositoryStack"

CLIENT_REGEX = "/(\\S+)"
SYNAPSER_CLIENT_PATTERN = SYNAPSER_CLIENT + CLIENT_REGEX
R_CLIENT_PATTERN = R_CLIENT + CLIENT_REGEX
PYTHON_CLIENT_PATTERN = PYTHON_CLIENT + CLIENT_REGEX
WEB_CLIENT_PATTERN = WEB_CLIENT + CLIENT_REGEX
OLD_JAVA_CLIENT_PATTERN = OLD_JAVA_CLIENT + CLIENT_REGEX
JAVA_CLIENT_PATTERN = JAVA_CLIENT + CLIENT_REGEX
COMMAND_LINE_CLIENT_PATTERN = COMMAND_LINE_CLIENT + CLIENT_REGEX
ELB_CLIENT_PATTERN = ELB_CLIENT + CLIENT_REGEX
STACK_CLIENT_PATTERN = STACK_CLIENT + CLIENT_REGEX


# Get access record from source and create dynamic frame for futher processing
def get_dynamic_frame(connection_type, file_format, source_path, glue_context):
    dynamic_frame = glue_context.create_dynamic_frame.from_options(
        format_options={"multiline": True},
        connection_type=connection_type,
        format=file_format,
        connection_options={
            "paths": [source_path],
            "recurse": True,
        },
        transformation_ctx="dynamic_frame")
    return dynamic_frame


# There are many fields in access records, however we need some of them for further processing
def apply_mapping(dynamic_frame):
    mapped_dynamic_frame = ApplyMapping.apply(
        frame=dynamic_frame,
        mappings=[
            ("payload.sessionId", "string", "SESSION_ID", "string"),
            ("payload.timestamp", "long", "TIMESTAMP", "long"),
            ("payload.userId", "int", "USER_ID", "int"),
            ("payload.method", "string", "METHOD", "string"),
            ("payload.requestURL", "string", "REQUEST_URL", "string"),
            ("payload.userAgent", "string", "USERAGENT", "string"),
            ("payload.host", "string", "HOST", "string"),
            ("payload.origin", "string", "ORIGIN", "string"),
            ("payload.xforwardedFor", "string", "X_FORWARDED_FOR", "string"),
            ("payload.via", "string", "VIA", "string"),
            ("payload.threadId", "long", "THREAD_ID", "long"),
            ("payload.elapseMS", "long", "ELAPSE_MS", "long"),
            ("payload.success", "boolean", "SUCCESS", "boolean"),
            ("payload.stack", "string", "STACK", "string"),
            ("payload.instance", "string", "INSTANCE", "string"),
            ("payload.date", "string", "DATE", "string"),
            ("payload.vmId", "string", "VM_Id", "string"),
            ("payload.returnObjectId", "string", "RETURN_OBJECT_ID", "string"),
            ("payload.queryString", "string", "QUERY_STRING", "string"),
            ("payload.responseStatus", "long", "RESPONSE_STATUS", "long"),
            ("payload.oauthClientId", "string", "OAUTH_CLIENT_ID", "string"),
            ("payload.basicAuthUsername", "string", "BASIC_AUTH_USERNAME", "string"),
            ("payload.authenticationMethod", "string", "AUTHENTICATION_METHOD", "string"),
        ],
        transformation_ctx="mapped_dynamic_frame")
    return mapped_dynamic_frame


# process the access record
def transform(dynamicRecord):
    dynamicRecord["NORMALIZED_METHOD_SIGNATURE"] = dynamicRecord["METHOD"] + " " + getNormalizedMethodSignature(
        dynamicRecord["REQUEST_URL"])
    dynamicRecord["CLIENT"] = getClient(dynamicRecord["USERAGENT"])
    dynamicRecord["CLIENT_VERSION"] = getClientVersion(dynamicRecord["CLIENT"], dynamicRecord["USERAGENT"])
    dynamicRecord["ENTITY_ID"] = getEntityId(dynamicRecord["REQUEST_URL"])
    timestamp = dynamicRecord["TIMESTAMP"]
    date = datetime.datetime.utcfromtimestamp(timestamp / 1000.0)
    dynamicRecord["YEAR"] = date.year
    dynamicRecord["MONTH"] = '%02d' % date.month
    dynamicRecord["DAY"] = '%02d' % date.day
    return dynamicRecord


def getNormalizedMethodSignature(requesturl):
    url = requesturl.lower()
    prefix_index = url.find('/v1/')
    if prefix_index == -1:
        raise ValueError("requestPath: " + requesturl + "was not correctly formatted. It must start with {optional "
                                                        "WAR name}/{any string}/v1/")
    else:
        start = prefix_index + 3
        requesturl = url[start:]
    if requesturl.startswith("/entity/md5"):
        result = "/entity/md5/#"
    elif requesturl.startswith("/evaluation/name"):
        result = "/evaluation/name/#"
    elif requesturl.startswith("/entity/alias"):
        result = "/entity/alias/#"
    else:
        result = re.sub("/(syn\\d+|\\d+)", "/#", requesturl)
    return result


def getClient(userAgent):
    if userAgent is None:
        result = "UNKNOWN"
    elif userAgent.find(WEB_CLIENT) >= 0:
        result = "WEB"
    elif userAgent.find(JAVA_CLIENT) >= 0:
        result = "JAVA"
    elif userAgent.find(OLD_JAVA_CLIENT) >= 0:
        result = "JAVA"
    elif userAgent.find(SYNAPSER_CLIENT) >= 0:
        result = "SYNAPSER"
    elif userAgent.find(R_CLIENT) >= 0:
        result = "R"
    elif userAgent.find(COMMAND_LINE_CLIENT) >= 0:
        result = "COMMAND_LINE"
    elif userAgent.find(PYTHON_CLIENT) >= 0:
        result = "PYTHON"
    elif userAgent.find(ELB_CLIENT) >= 0:
        result = "ELB_HEALTHCHECKER"
    elif userAgent.find(STACK_CLIENT) >= 0:
        result = "STACK"
    else:
        result = "UNKNOWN"
    return result


def getClientVersion(client, userAgent):
    if userAgent is None:
        return None
    elif client == "WEB":
        matcher = re.match(WEB_CLIENT_PATTERN, userAgent)
    elif client == "JAVA":
        if userAgent.startswith("Synpase"):
            matcher = re.match(OLD_JAVA_CLIENT_PATTERN, userAgent)
        else:
            matcher = re.match(JAVA_CLIENT_PATTERN, userAgent)
    elif client == "SYNAPSER":
        matcher = re.match(SYNAPSER_CLIENT_PATTERN, userAgent)
    elif client == "R":
        matcher = re.match(R_CLIENT_PATTERN, userAgent)
    elif client == "PYTHON":
        matcher = re.match(PYTHON_CLIENT_PATTERN, userAgent)
    elif client == "ELB_HEALTHCHECKER":
        matcher = re.match(ELB_CLIENT_PATTERN, userAgent)
    elif client == "COMMAND_LINE":
        matcher = re.match(COMMAND_LINE_CLIENT_PATTERN, userAgent)
    elif client == "STACK":
        matcher = re.match(STACK_CLIENT_PATTERN, userAgent)
    else:
        return None
    if matcher is None:
        return None
    else:
        return matcher.group(1)


def getEntityId(requesturl):
    if requesturl is None:
        return None
    else:
        matcher = re.search("/entity/(syn\\d+|\\d+)", requesturl)
        if matcher is None:
            return None
        else:
            entityId = matcher.group(1)
            if entityId.startswith("syn"):
                entityId = entityId[3:]
    return entityId


def main():
    # Get args and setup environment
    args = getResolvedOptions(sys.argv,
                              ["JOB_NAME", "S3_SOURCE_PATH", "S3_DESTINATION_PATH", "DESTINATION_FILE_FORMAT"])
    sc = SparkContext()
    glue_context = GlueContext(sc)
    spark = glue_context.spark_session
    job = Job(glue_context)
    job.init(args["JOB_NAME"], args)

    dynamic_frame = get_dynamic_frame("s3", "json", args["S3_SOURCE_PATH"], glue_context)
    mapped_dynamic_frame = apply_mapping(dynamic_frame)
    transFormed_dynamic_frame = mapped_dynamic_frame.map(f=transform)

    #  Write the processed access records to destination
    write_dynamic_frame = glue_context.write_dynamic_frame.from_options(
        frame=transFormed_dynamic_frame,
        connection_type="s3",
        format=args["DESTINATION_FILE_FORMAT"],
        connection_options={
            "path": args["S3_DESTINATION_PATH"],
            "compression": "gzip",
            "partitionKeys": ["YEAR", "MONTH", "DAY"],
        },
        transformation_ctx="write_dynamic_frame")

    job.commit()


if __name__ == "__main__":
    main()
