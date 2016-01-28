# =============================================================================
# Blast - Client editorial creator
# One item
# Another item
# =============================================================================
import json
import os
import tempfile
import subprocess
import re

from blurdev.action import *
from blur3d.actions.farm import FarmAction, Services

import blurdev
import blursg
from trax.api import data

from trax.api.data import Shot, Asset, Software, FileType, File

# =============================================================================
# EXCEPTIONS
# =============================================================================
class BlastExecutionException(subprocess.CalledProcessError):
	pass

# =============================================================================
# CLASSES
# =============================================================================


class RunNukeBlast(FarmAction):
	def __init__(self, *args, **kwargs):
		super(RunNukeBlast, self).__init__(*args, **kwargs)
		self.services.append(Services.Nuke9)

	@argproperty(atype=App, default=Apps.Nuke)
	def application(self):
		pass

	@argproperty(atype=bool, default=False)
	def applyDistortion(self):
		pass

	@argproperty(atype=bool, default=False)
	def applyUndistortion(self):
		pass

	@argproperty(atype=bool, default=False)
	def applyPostmove(self):
		pass

	@argproperty(atype=basestring, default="")
	def artistName(self):
		pass

	@argproperty(atype=Asset, default=Asset())
	def asset(self):
		pass

	@argproperty(atype=bool, default=False)
	def createSlate(self):
		pass

	@argproperty(atype=basestring, default="")
	def filetype(self):
		""" This is the file type that is used with this particular action."""
		pass

	@argproperty(atype=bool, default=False)
	def noAudio(self):
		pass

	@argproperty(atype=bool, default=False)
	def noColor(self):
		pass

	@argproperty(atype=bool, default=False)
	def noCDL(self):
		pass

	@argproperty(atype=bool, default=False)
	def noLUT(self):
		pass

	@argproperty(atype=basestring, default="")
	def inputFilepath(self):
		"""
		The input frames that you would like to blast.
		This should use a #### as a frame counter.
		"""
		pass

	@argproperty(atype=basestring, default="")
	def formats(self):
		""" A space separated string of all the formats to run for this blast."""
		pass

	@argproperty(atype=int, default=0)
	def framein(self):
		""" In frame """
		pass

	@argproperty(atype=int, default=0)
	def frameout(self):
		""" Out frame """
		pass

	@argproperty(atype=str, default="")
	def name(self):
		""" Client name for the burn-in/slate. """
		pass

	@argproperty(atype=basestring, default="")
	def notes(self):
		""" Notes for the burn-in/slate. """
		pass

	@argproperty(atype=basestring, default="")
	def output(self):
		""" Output file path. """
		pass

	@argproperty(atype=basestring, default="")
	def outputFilename(self):
		""" File pattern must contain a #### """
		pass

	@argproperty(atype=basestring, default="")
	def overrideCompVariation(self):
		""" This is an override variation from the shot composition.  This
		is mainly used if there is something needed per shot.  This property
		along with the shot property will pull the comp file needed from
		trax and use that as the nuke comp.
		"""
		pass

	@argproperty(atype=bool, default=False)
	def postviz(self):
		""" ** TO BE DEPRECATED ** """
		pass

	@argproperty(atype=basestring, default="")
	def preset(self):
		""" This is an override for allowing to blast based off presets."""
		pass

	@argproperty(atype=bool, default=False)
	def marketing(self):
		""" **TO BE DEPRECATED** """
		pass

	@argproperty(atype=int, default=20)
	def priority(self):
		""" Priority for assfreezer. """
		pass

	@argproperty(atype=Shot, default=Shot())
	def shot(self):
		""" The shot for the current blast. """
		pass

	@argproperty(atype=basestring, default="")
	def version(self):
		""" String of the version number. """
		pass

	def getApplicationExecutable(self, application=None):
		""" Returns the application. """
		application = application or self.application
		executables = {}
		s = Software.recordByName('Nuke 9.0')
		executables['Nuke'] = os.path.join(unicode(s.installedPath()), unicode(s.executable()))
		return executables.get(str(application), None)

	def getProjectPrefs(self):
		""" Returns the file path to the projects blast prefs files. """
		if not self.project.isRecord():
			return ""
		aType = data.AssetType.recordByName("Project")
		fType = data.FileType.recordByAssetTypeAndId(aType, "Blast::Prefs")
		prefsPath = fType.fullPath(self.project)
		if not os.path.exists(prefsPath):
			# Use the prefs stored in _virtual_project as a default to fall back on
			# if the current project doesn't have a prefs file.
			prefsPath = fType.fullPath(data.Project.recordByName('_virtual_project'))
		return prefsPath

	def getNukeProjectPath(self):
		""" Returns the file path to the projects nuke template files. """
		if not self.project.isRecord():
			return ""
		aType = data.AssetType.recordByName("Project")
		fType = data.FileType.recordByAssetTypeAndId(aType, "Blast::Nuke")
		nukeProjectPath = fType.fullPath(self.project)
		return nukeProjectPath

	def getCompVariationFile(self):
		""" Retrieve the comp variation file. """
		shotCompFileType = FileType.recordByUniqueId("Shot::Composition")
		tCompFile = File.findLatestVersionByElementAndFileType(
			self.shot,
			shotCompFileType,
			variation=self.overrideCompVariation
		)
		compFile = None
		if tCompFile.isRecord():
			compFile = tCompFile.fullPath()
		return compFile

	def overrideFileType(self):
		""" This defines what file type to use."""
		# This key defines which nuke file to load up.
		# This is defined in the nukefiles.json file
		if self.filetype:
			return
		if self.marketing:
			key = "marketing"
		elif self.postviz:
			key = "postviz"
		else:
			key = "comp"
		# Sort of hacky right now but we want to be able to ingest plate
		# format.  If so, you want to use another nuke file for that
		formats = self.formats.split(' ')
		if "PLATE" in formats and not self.filetype:
			key = "plate"
		self.filetype = key

	def run(self):
		""" Builds the nuke command to run for generating formats.

		Args:
			None

		Returns:
			None

		Raises:
			None

		"""
		self.setArgsFromPresets()
		# Prefs and Nuke files stored in a blast location
		prefsPath = self.getProjectPrefs()
		nukeProjectPath = self.getNukeProjectPath()
		nukeFilesJsonPath = os.path.normpath(
			os.path.join(prefsPath, "nukefiles.json")
		)
		with open(nukeFilesJsonPath, "r") as fileinfo:
			filesdata = fileinfo.read()
		nukefiles = json.loads(filesdata)
		self.overrideFileType()
		nukeComp = None
		# If provided an override comp variation,
		# Attempt to find the comp file and use it.
		if self.overrideCompVariation and self.shot:
			nukeComp = self.getCompVariationFile()
			# Use the default comp if none is found.
			if not nukeComp:
				self.filetype = "default"
		if not nukeComp:
			nukeComp = os.path.join(
				nukeProjectPath,
				nukefiles[self.filetype]["location"]
			)
		if self.outputFilename:
			# Check for a #### frame token
			if "####" not in self.outputFilename:
				filename = self.outputFilename + ".####"
			else:
				filename = self.outputFilename
		else:
			filename = os.path.splitext(os.path.basename(self.inputFilepath))[0]
		if self.application == Apps.Nuke:
			tempDir = tempfile.mkdtemp()
			pickleFile = os.path.join(tempDir, 'action.pickle')
			self.pickle(pickleFile)
			inputFilepath = self.inputFilepath.replace("\\", "/")
			output = self.output.replace("\\", "/")
			cmdArgs = [
				self.getApplicationExecutable(),
				'-t',
				os.path.join(os.path.dirname(__file__), "run.py"),
				nukeComp,
				'--file',
				inputFilepath,
				'--filename',
				filename,
				'--output',
				output,
				'--framein',
				str(self.framein),
				'--frameout',
				str(self.frameout),
				'--formatsfile',
				str(os.path.join(prefsPath, "formats.json")),
			]
			if self.notes:
				cmdArgs.extend(["--notes", self.notes])
			if self.artistName:
				cmdArgs.extend(["--artist", self.artistName])
			if self.name:
				cmdArgs.extend(["--clientShotName", self.name])
			if self.version:
				cmdArgs.extend(["--version", self.version])
			if self.shot.isRecord():
				cmdArgs.extend(["--shot", str(self.shot.displayName()).replace(" ", "_")])
			if self.asset.isRecord():
				cmdArgs.extend(["--asset", str(self.asset.displayName())])
			if self.project.isRecord():
				cmdArgs.extend(["--project", str(self.project.name())])
			# If no formats are present, use the default
			if not self.formats:
				self.formats = "DEFAULT"
			cmdArgs.append('--formats')
			cmdArgs.extend(self.formats.split(' '))
			if self.createSlate:
				cmdArgs.append('--createSlate')
			if self.noLUT:
				cmdArgs.append('--nolut')
			if self.noCDL:
				cmdArgs.append('--nocdl')
			if self.applyDistortion:
				cmdArgs.append('--applyDistortion')
			if self.applyUndistortion:
				cmdArgs.append('--applyUndistortion')
			if self.applyPostmove:
				cmdArgs.append('--applyPostmove')
			if self.noAudio:
				cmdArgs.append('--noaudio')
			cmdArgs.append('--runffmpeg')
			print " ".join(cmdArgs)
			# Ensure we don't get a DOS window popping up when shelling
			# to python.
			flags = subprocess.STARTUPINFO()
			flags.dwFlags |= subprocess.STARTF_USESHOWWINDOW
			response = subprocess.Popen(
				cmdArgs,
				stdin=subprocess.PIPE,
				stdout=subprocess.PIPE,
				stderr=subprocess.PIPE,
				startupinfo=flags,
				shell=True,
			)
			output, error = response.communicate()
			rc = response.returncode
			if rc != 0:
				print error
				raise BlastExecutionException(rc, " ".join(cmdArgs), error)
			else:
				print output
				return (rc, output)
		else:
			raise NotImplementedError(
				"Build Process is not implemented for {0}.".format(
					str(self.application),
				)
			)

	@executehook(Apps.XSI)
	def launchFromXSIAndRunComp(self):
		self.run()

	@executehook(Apps.Max)
	def launchFromMaxAndRunComp(self):
		self.run()

	@executehook(Apps.External)
	def launchApplicationAndRunComp(self):
		self.run()


	def setArgsFromPresets(self):
		""" Retrieve settings from a presets prefs file to
		set on the blast object.
		"""
		# If there is no preset no need to set arguments
		if not self.preset:
			return
		prefsPath = self.getProjectPrefs()
		presetsPath = os.path.normpath(
			os.path.join(prefsPath, "presets.json")
		)
		with open(presetsPath, "r") as fileinfo:
			filesdata = fileinfo.read()
		presets = json.loads(filesdata)
		presetSettings = presets.get(self.preset)
		if presetSettings:
			# Attempt to eval the value if possible
			for attr, value in presetSettings.iteritems():
				try:
					if isinstance(value, unicode):
						value = str(value)
					setattr(self, attr, value)
				except (NameError, SyntaxError) as e:
					setattr(self, attr, str(value))
