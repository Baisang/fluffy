import os
import pipes
import requests
import json
from fluffy.utils import get_human_size
from django.conf import settings

"""Backends handle storing of uploaded files. A backend should implement
__init__(self, options) where options will be the dict of options given in the
fluffy settings, and store(self, stored_file) which stores an uploaded file.

All other details are left up to your implementation."""

class FileBackend:
	"""Storage backend which stores files and info pages on the local disk."""

	def __init__(self, options):
		self.options = options

	def store(self, stored_file):
		"""Stores the file and its info page. This is the only method
		which needs to be called in order to persist the uploaded file to
		the storage backend."""
		path = self.options["file_path"].format(name=stored_file.name)
		info_path = self.options["info_path"].format(name=stored_file.name)

		try:
			# store the file itself
			print("Writing to {}...".format(path))
			with open(path, "wb+") as dest:
				for chunk in stored_file.file.chunks():
					dest.write(chunk)

			# store the info page
			print("Writing info page to {}...".format(info_path))
			with open(info_path, "wb+") as dest:
				dest.write(stored_file.info_html.encode("utf-8"))
		except IOException as e:
			internal = "Received IOException: {}".format(e)
			display = "Sorry, we weren't able to save your file."
			raise BackendException(internal, display)

class S3CommandLineBackend:
	"""Storage backend which uploads to S3 using AWS' command-line tools.

	We use the command-line tools because at the time of writing, boto does not
	support python3. Once this changes, it will be trivial to switch out the
	commands used for uploading.

	For this backend to work, you must have awscli installed and configured.

	For installation, try: pip install awscli
	For configuration, try: aws configure

	To verify everything works, try: aws s3 ls
	You should see a list of your S3 buckets."""

	def __init__(self, options):
		self.options = options

	def store(self, stored_file):
		"""Stores the file and its info page. This is the only method
		which needs to be called in order to persist the uploaded file to
		the storage backend."""

		def write_file(dest):
			for chunk in stored_file.file.chunks():
				dest.write(chunk)

		def write_info(dest):
			dest.write(stored_file.info_html.encode("utf-8"))

		files = (
			{"name": "file", "write": write_file},
			{"name": "info", "write": write_info}
		)

		for file in files:
			name = self.options[file["name"] + "_name"].format(name=stored_file.name)
			path = self.options["tmp_path"].format(name=name)

			print("Writing temp file '{}' to '{}'".format(name, path))

			with open(path, "wb+") as dest:
				file["write"](dest)

			s3 = self.options[file["name"] + "_s3path"].format(name=stored_file.name)

			cmd = "aws s3 cp {} {}".format(pipes.quote(path), pipes.quote(s3))
			print("Uploading to S3 with command: {}".format(cmd))
			status = os.system(cmd)

			if status != 0:
				internal = "Received {} status code for command {}".format(status, cmd)
				display = "Sorry, we weren't able to save your file."
				raise BackendException(internal, display)

			os.remove(path)

class KloudlessBackend:
	"""Storage backend which uploads files via the Kloudless API. This is an
	easy way to upload to S3, Dropbox, and several other services."""

	API_ENDPOINT = "https://api.kloudless.com/v0"
	API_RESOURCE_FILE = "/accounts/{account}/files"

	def __init__(self, options):
		self.options = options

	def store(self, stored_file):
		# TODO: use multipart upload API for large files
		url = self.API_ENDPOINT + self.API_RESOURCE_FILE

		def upload(name, parent_id, file):
			metadata = {"name": name, "parent_id": parent_id}
			headers = {"Authorization": "AccountKey " + self.options["account_key"]}

			req = requests.post(url.format(account=self.options["account_id"]),
				{"metadata": json.dumps(metadata)},
				headers=headers,
				files={"file": file})

			if req.status_code != 201:
				print("Got unexpected status code from Kloudless: {}"
					.format(req.status_code))
				print("Response: {}".format(req.text))

				internal = "Received {} status code".format(req.status_code)
				display = "Sorry, we weren't able to save your file."
				raise BackendException(internal, display)

		files = (
			{"name": "file", "file": stored_file.file},
			{"name": "info", "file": ("info.html", stored_file.info_html)}
		)

		for file in files:
			name = self.options[file["name"] + "_name"].format(name=stored_file.name)
			parent_id = self.options[file["name"] + "_parent_id"]

			upload(name, parent_id, file["file"])

		print("Done!")



class DebugBackend:
	"""Storage backend which doesn't store files but prints debug info."""

	def __init__(self, options):
		self.options = options

	def store(self, stored_file):
		"""Stores the file and its info page. This is the only method
		which needs to be called in order to persist the uploaded file to
		the storage backend."""

		print("Storing file:")
		print("\tName: {}".format(stored_file.name))
		print("\tSize: {}".format(get_human_size(stored_file.file.size)))

class BackendException(Exception):
	"""Exception to be raised when a backend encounters an error trying to store
	a file. user_message will be displayed to the user, internal_message will
	be logged and not displayed.

	BackendException will display a "friendly" message to the user. All other
	uncaught exceptions will display a generic error.
	"""
	def __init__(self, internal_message, display_message):
		self.display_message = display_message
		Exception.__init__(self, internal_message)

backends = {
	"file": FileBackend,
	"s3cli": S3CommandLineBackend,
	"kloudless": KloudlessBackend,
	"debug": DebugBackend
}

def get_backend():
	"""Returns a backend instance as configured in the settings."""
	conf = settings.STORAGE_BACKEND
	name, options = conf["name"], conf["options"]

	return backends[name](options)
