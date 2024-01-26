import boto3
import os
import sys
import uuid
from datetime import datetime
from urllib.parse import unquote_plus
from PIL import Image
            
s3_client = boto3.client('s3')
thumbnail_size = 300, 300
temporary_path = '/tmp'
originals_prefix = 'uploads/'
images_prefix = 'images/'
thumbnails_prefix = 'thumbs/'
            
def resize_image(image_path, thumbnail_path):
  with Image.open(image_path) as image:
    image.thumbnail(thumbnail_size)
    image.save(thumbnail_path)
    return image.get_format_mimetype()

def get_safe_object_key(key):
  return key.replace('/', '')

def get_record_bucket_name(record):
  return record['s3']['bucket']['name']

def get_record_object_key(record):
  return unquote_plus(record['s3']['object']['key'])

def get_original_path(bucket_name, key):
  return '{}/{}{}'.format(temporary_path, uuid.uuid4(), get_safe_object_key(key))

def get_thumbnail_path(bucket_name, key):
  return '{}/{}'.format(temporary_path, get_safe_object_key(key))

def get_thumbnail_key(timestamp, file_uuid, extension):
  return '{}{}_{}{}'.format(thumbnails_prefix, timestamp, file_uuid, extension)

def get_destination_key(timestamp, file_uuid, extension):
  return '{}{}_{}{}'.format(images_prefix, timestamp, file_uuid, extension)

def process_record(record):
  bucket_name = get_record_bucket_name(record)
  original_key = get_record_object_key(record)
  original_path = get_original_path(bucket_name, original_key)
  thumbnail_path = get_thumbnail_path(bucket_name, original_key)
  timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
  file_uuid = uuid.uuid4()
  extension = os.path.splitext(original_key)[1]
  thumbnail_key = get_thumbnail_key(timestamp, file_uuid, extension)
  destination_key = get_destination_key(timestamp, file_uuid, extension)
  s3_client.download_file(bucket_name, original_key, original_path)
  mime_type = resize_image(original_path, thumbnail_path)
  s3_client.upload_file(thumbnail_path, bucket_name, thumbnail_key, ExtraArgs={'ContentType': mime_type})
  s3_client.copy_object(Bucket=bucket_name, CopySource=bucket_name + '/' + original_key, Key=destination_key, ContentType=mime_type)
  s3_client.delete_object(Bucket=bucket_name, Key=original_key)

def handler(event, context):
  for record in event['Records']:
    process_record(record)
