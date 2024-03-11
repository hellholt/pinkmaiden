import json
import boto3
from datetime import datetime
import os

s3_client = boto3.client('s3')
bucket_name = os.environ['BUCKET_NAME']
domain_name = os.environ['DOMAIN_NAME']
max_count = 100

def get_object_data(object):
  key = object.get('Key', 'WTF')
  try:
    stamp = key.split('/')[1].split('-')[0]
  except:
    stamp = 'WTF'
  try:
    uuid = key.split('/')[1].split('_')[1].split('.')[0]
  except:
    uuid = 'WTF'
  return {
    'key': key,
    'thumbnail_url': f'https://{domain_name}/{key}',
    'image_url': f'https://{domain_name}/{key.replace("thumbs/", "images/")}',
    'stamp': stamp,
    'uuid': uuid,
  }

def handler(event, context):
  query_params = event.get('queryStringParameters', {})
  if not query_params:
    query_params = {}
  checkpoint = query_params.get('checkpoint', '0')
  count = int(query_params.get('count', max_count))
  count = min(count, max_count)
  response = s3_client.list_objects_v2(
    Bucket=bucket_name,
    Prefix='thumbs/',
    MaxKeys=count,
    StartAfter=f'thumbs/{checkpoint}',
  )
  images = [obj for obj in response.get('Contents', [])]
  images.sort(key=lambda x: x['Key'])
  data = {}
  data['images'] = [get_object_data(image) for image in images]
  return {
    'statusCode': 200,
    'headers': {
      'Content-Type': 'application/json'
    },
    'body': json.dumps(data)
  }

