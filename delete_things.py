import boto3
import sys
from os.path import basename

s3_client = boto3.client('s3')
with open(sys.argv[1]) as f:
  lines = [basename(line.strip()) for line in f.readlines() if line.strip()]
  objects = []
  objects += [{"Key": "images/" + line.strip()} for line in lines]
  objects += [{"Key": "thumbs/" + line.strip()} for line in lines]
  result = s3_client.delete_objects(Bucket='darkdell.pnk',
    Delete={
      "Objects": objects,
    })
  print(result)
