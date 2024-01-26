#!/usr/bin/env bash

# Ensure that the `terraform` directory is properly formatted.
terraform fmt -check=true -diff=true -recursive terraform
