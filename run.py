
# Built-in
import argparse
from datetime import datetime
import json
import re
import os
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

# Nuke
import nuke

# Blur
# import blurdev
from blur3d.pipe.cinematic.api.filesequence import FileSequence
from blur3d.actions.ffmpeg import RunFFMpeg
import trax
try:
	import blursg
except ImportError as e:
	print "Unable to import blursg.  Please contact Pipeline to get the new custom nuke install"

"""
-y - override output files
-f - force format

"""

# apcs == Prores
# avc1 == H264
ffmpegargs = {
	"apcs" : "C:/Program Files/ffmpeg/bin/ffmpeg.exe -y -probesize 5000000 -start_number {framestart} -f image2 -r {fps} -i {filesequence} -codec:v prores -profile:v 1 -pix_fmt yuv422p10le -qscale:v 5 -vendor ap10 -r {fps} -y {output}",
	"avc1" : "ffmpeg -start_number {framestart} -r {fps} -i {filesequence} -i {audio} -f mov -pix_fmt yuv420p -vcodec h264 -preset slow -b:v 10M -y {output}"
}

def parseArgs():
	parser = argparse.ArgumentParser(description="Blast some files.")
	parser.add_argument('comp', type=str, help='File location for the comp script to be used.')
	parser.add_argument('-t', '--formats', type=str, nargs='+', help='Formats to produce')
	parser.add_argument('-k', '--formatsfile', type=str, help='Formats location')
	parser.add_argument('-f', '--file', type=str, help='Image file to produce')
	parser.add_argument('-n', '--notes', type=str, help='Notes for the client')
	parser.add_argument('-g', '--filename', type=str, help='Filename to be burned in')
	parser.add_argument('-a', '--artist', type=str, help='Artist to place in burn in')
	parser.add_argument('-o', '--output', type=str, help='Output directory')
	parser.add_argument('-i', '--framein', type=int, help='The in frame', default=0)
	parser.add_argument('-j', '--frameout', type=int, help='The out frame', default=0)
	parser.add_argument('-c', '--clientShotName', type=str, help='Client Shot Name')
	parser.add_argument('-v', '--version', type=str, help='Client Version')
	parser.add_argument('-p', '--project', type=str, help='Project for the blast')
	parser.add_argument('-s', '--shot', type=str, help='Shot for the blast')
	parser.add_argument('-b', '--asset', type=str, help='Asset for the blast')
	parser.add_argument('--applyDistortion', dest='applyDistortion', action='store_true')
	parser.add_argument('--applyUndistortion', dest='applyUndistortion', action='store_true')
	parser.add_argument('--applyPostmove', dest='applyPostmove', action='store_true')
	parser.add_argument('--createSlate', dest='createSlate', action='store_true')
	parser.add_argument('--runffmpeg', dest='runffmpeg', action='store_true')
	parser.add_argument('--nocdl', dest='nocdl', action='store_true')
	parser.add_argument('--nolut', dest='nolut', action='store_true')
	parser.add_argument('--noaudio', dest='noaudio', action='store_true')
	parsedArgs = parser.parse_args()
	return parsedArgs

def setTextOptions(node):
	fontSize = node.knob("font_size")
	fontSize.setValue(40)

def addAudio(outputNode, project, shot):
	""" Add an audio file path to the output node from shotgun.

	Args:
		outputNode(Node) : The output write node for nuke to apply the audio.
		project(str) : The name of the project to retrieve audio from.
		shot(str) : The name of the shot to retrieve audio from.

	Returns:
		None

	"""
	normalizedAudioPath = ""
	sg = blursg.sg()
	sgProject = sg.find_one("Project", [["name", "is", project]], [])
	sgShot = sg.find_one("Shot", [["project", "is", sgProject], ["code", "is", shot]])
	audio = sg.find_one(
		"Version",
		[
			['entity', 'is', sgShot],
			['sg_version_type', 'is', 'Audio']
		],
		['sg_path_to_movie'],
		[{'field_name': 'sg_version_number', 'direction' : 'desc'}]
	)
	if audio:
		normalizedAudioPath = audio['sg_path_to_movie'].replace("\\", "/")
		if outputNode['file_type'].value() == 'mov':
			outputNode["mov64_audiofile"].setValue(normalizedAudioPath)
			outputNode["mov32_audiofile"].setValue(normalizedAudioPath)
	return normalizedAudioPath

def applyDistortion(formatinfo, project, shot, distort=True):
	""" Pulls the distortion map from the shot, and switches the script to
	use the distortion map.

	Args:
		formatinfo(dict) : Dictionary with custom settings for the project.
		project(str) : Name of the project to retrieve the distortion maps.
		shot(str) : Name of the shot to retrieve the distortion maps.
		distort(bool) : If True, a distortion map will be applied.  Undistort otherwise.

	"""
	if distort:
		variation = "Distorted"
	else:
		variation = "Undistorted"
	distortNodeName = formatinfo.get('distortion_node')
	distortSwitchName = formatinfo.get('distortion_switch')
	if not distortNodeName:
		return
	sg = blursg.sg()
	sgProject = sg.find_one("Project", [["name", "is", project]], [])
	sgShot = sg.find_one("Shot", [["project", "is", sgProject], ["code", "is", shot]])
	stmap = sg.find_one(
		"Version",
		[
			['entity', 'is', sgShot],
			['sg_version_type', 'is', 'ST Map'],
			['sg_variation', 'is', variation]
		],
		['sg_path_to_movie'],
		[{'field_name': 'sg_version_number', 'direction' : 'desc'}]
	)
	if stmap:
		distortNode = nuke.toNode(distortNodeName)
		if distortSwitchName:
			distortSwitch = nuke.toNode(distortSwitchName)
		else:
			distortSwitch = None
		if distortNode or distortSwitch:
			normalizedSTMapPath = stmap['sg_path_to_movie'].replace("\\", "/")
			distortNode["file"].setValue(normalizedSTMapPath)
			if distortSwitch:
				distortSwitch["which"].setValue(1)

def getPostmove(formatinfo, project, shot):
	""" Checks the shot to see if there is a Postmove version linked.

	Args:
		formatinfo(dict) : Mapping of custom settings for the project
		project(str) : Name of the project to retrieve for the post move
		shot(str) : Name of the shot to retrieve for the post move

	Returns:
		Dict - Returns a dictionary that contains the path to the postmove

	"""
	sg = blursg.sg()
	sgProject = sg.find_one("Project", [["name", "is", project]], [])
	sgShot = sg.find_one("Shot", [["project", "is", sgProject], ["code", "is", shot]])
	sgPostmove = sg.find_one(
		"Version",
		[
			['entity', 'is', sgShot],
			['sg_version_type', 'is', 'Composition'],
			['sg_variation', 'is', 'Postmove'],
			['sg_status_list', 'is', 'apr']
		],
		['sg_path_to_movie'],
		[{'field_name': 'sg_version_number', 'direction' : 'desc'}]
	)
	return sgPostmove

def applyPostmove(formatinfo, project, shot, readnode):
	""" Looks for the postmove nuke script for this particular shot, and applies
	a post move node to the script.

	Args:
		formatinfo(dict) : Mapping of custom settings for the project
		project(str) : Name of the project to retrieve for post move
		shot(str) : Name of the shot to retrieve for the post move
	"""
	sgPostmove = getPostmove(formatinfo, project, shot)
	if sgPostmove:
		# Retrieve the node from the nuke path specified
		postmoveNode = nuke.nodePaste(sgPostmove['sg_path_to_movie'])
		# Arrange the input settings to ensure that the postmove node is right
		# after the read node
		# Possibly a bug, when attempting to retrieve the dependent nodes
		# it comes as an empty less.  However, when requerying a second time
		# it populates.
		readnode.dependent()
		# This should be the reformat node
		# We want to connect the postmove like this
		# [ReadNode]--->[Reformat]--->[Postmove]--->[...]
		reformatNode = readnode.dependent(nuke.INPUTS)[0]
		dependentNodes = reformatNode.dependent()
		postmoveNode.setInput(0, reformatNode)
		for dependentNode in dependentNodes:
			dependentNode.setInput(0, postmoveNode)

def editSlate(blastOptions, formatinfo, framein, frameout):
	""" Adjust slate information using the blast options.

	Args:
		blastOptions(argparse.Namespace) : Options brought from argument parser
		formatinfo(dict) : Dictionary of blast format options
		framein(int) : First frame
		frameout(int) : Last frame

	Returns:
		None

	"""
	# Edit the slate
	slateAttrMap = {
		"notes" : blastOptions.notes,
		"clientshot" : blastOptions.clientShotName,
		"version" : blastOptions.version,
		"frames" : "{0}-{1}".format(framein+1, frameout)
	}
	slateNodeName = formatinfo.get('slate_node')
	if slateNodeName:
		slateNode = nuke.toNode(slateNodeName)
		if slateNode:
			for attr, value in slateAttrMap.iteritems():
				slateNode[attr].setValue(value)
				# setTextOptions(slateNode)

def editBurnin(blastOptions, formatinfo):
	""" Adjust burnins using the blast options

	Args:
		blastOptions(argparse.Namespace) : Options brought from argument parser
		formatinfo(dict) : Dictionary of blast format options
		framein(int) : First frame
		frameout(int) : Last frame

	Returns:
		None

	"""
	# TODO Allow user to specify burnin node from the blast prefs
	# TODO Allow user to specify different properties for burnin
	burninNodeName = "Burnin"
	knobAttrMap = {
		"notes" : blastOptions.notes,
		"clientShotName" : blastOptions.clientShotName,
		"artist" : blastOptions.artist,
	}

	# nodename : [knobkey, knobvalue]
	if blastOptions.version:
		clientShotText = "{0}_{1}".format(blastOptions.clientShotName, blastOptions.version)
	else:
		clientShotText = blastOptions.clientShotName
	burninNode = nuke.toNode(burninNodeName)
	if not burninNode:
		print "No Burnin node exists.  Skipping the burnin process."
		return False
	for knobName, knobAttr in knobAttrMap.iteritems():
		try:
			burninNode.knob(knobName).setValue(knobAttr)
		except AttributeError:
			pass

def getFrameRange(formatinfo, blastOptions, nodeinstring, nodeoutstring):
	nodein = nuke.toNode(nodeinstring)
	nodeout = nuke.toNode(nodeoutstring)
	framein = blastOptions.framein
	frameout = blastOptions.frameout
	# If the frame in/out are 0, use the node frame in/out
	if framein == 0 and frameout == 0:
		framerange = nodein.frameRange()
		framein = framerange.first()
		frameout = framerange.last()
	# If single frame is specified, use only first frame
	if formatinfo.get('single_frame'):
		frameout = framein
	nodein['first'].setValue(framein)
	nodein['last'].setValue(frameout)
	nodeout['first'].setValue(framein)
	nodeout['last'].setValue(frameout)
	return (framein, frameout)

def keySlate(formatinfo, framein):
	""" Remove keys from the slate and re-adjust slate keys based
	on frame range.
	"""
	switchName = formatinfo.get("slate_switch")
	if switchName:
		k = nuke.toNode(switchName)["which"]
		k.setAnimated()
		for curve in k.animations():
			curve.clear()
		k.setValueAt(0, framein)
		k.setValueAt(1, framein + 1)

def openComp(filepath):
	nuke.scriptOpen(filepath)

def render(node, start, end, increment=1):
	nuke.execute(node, start, end, increment)

def runffmpegaction(framein, filesequence, audio, projectname, shotname=None, assetname=None):
	"""
	Runs an ffmpeg command on a given file sequence
	"""
	project = trax.api.data.Project.recordByName(projectname)
	output = filesequence.replace(".%04d", "")
	outputpath = os.path.splitext(output)[0] + ".mov"
	# Build Inputs and Outputs Specifications
	inputs  = [{
		'filename' : filesequence,
		'startFrame' : framein,
		'framerate' : 23.976
	}]
	# If we have an audio file, add it as an input as well
	if audio and os.path.exists(audio):
		inputs.append({'filename' : audio})
	outputs = [{
		'filename' : outputpath,
		'forceFormat' : 'mov',
		'pixelFormat' : 'yuv420p',
		'videoCodec' : 'h264',
		'preset' : 'fast',
		'videoBitrate' : '5M',
		'maxrate' : '5M',
		'overwriteExisting' : None,
		'fps' : 23.976,
	}]
	job = "FFMPEG H264 {0}__{1}".format(projectname, os.path.basename(outputpath))
	kwargs = {
		"inputs" : inputs,
		"outputs" : outputs,
		"project" : project,
		"job" : job,
		"runLocal" : True,
	}
	blastBackupDir = getBlastBackupNukeDir(projectname, shotname, assetname)
	datestr = datetime.now().strftime("%m_%d_%y_%H_%M")
	basename = "{0}_{1}_{2}.bat".format("FFMPEG",shotname, datestr)
	ffmpegLog = os.path.join(blastBackupDir, basename)
	action = RunFFMpeg(**kwargs)
	# Write the command in a log file to be re run if necessary
	with open(ffmpegLog, "w") as logfile:
		logfile.write(action.buildWindowsCommand())
	action()

def runffmpeg(framein, filesequence, audio, formatinfo):
	"""
	Runs an ffmpeg command on a given file sequence
	"""
	codec = formatinfo['codec']
	output = filesequence.replace("_%04d", "")
	outputpath = os.path.splitext(output)[0] + ".mov"
	ffmpegTemplateCmd = ffmpegargs[codec]
	kwargs = {
		"framestart" : framein,
		"filesequence" : filesequence,
		"fps" : str(23.976),
		"output" : outputpath,
		"audio" : audio
	}
	# If there is no audio, remove audio from command template
	if not audio:
		ffmpegTemplateCmd = re.sub("-i {audio} ", "", ffmpegTemplateCmd)
		del kwargs['audio']
	ffmpegcmd = ffmpegTemplateCmd.format(**kwargs)
	print "FFMPEG COMMAND: {0}".format(ffmpegcmd)
	process = subprocess.Popen(
		ffmpegcmd.split(" "),
		shell=True,
		stdout=subprocess.PIPE,
		stderr=subprocess.PIPE
	)
	output, err = process.communicate()
	print output
	print err

def setImageSequence(imageSeq, innode):
	fileKnob = innode.knob("file")
	fileKnob.setValue(imageSeq)

def setOutputNode(nodeout, blastOptions, formatinfo, filename):
	# Create directory if it doesen't exists.  Or else Nuke will get
	# mad at you for it.
	relativePath = formatinfo.get("relative_path")
	if relativePath:
		formatoutputpath = "/".join([blastOptions.output, relativePath])
	else:
		formatoutputpath = blastOptions.output
	if not os.path.exists(formatoutputpath):
		try:
			os.makedirs(formatoutputpath)
		except WindowsError as e:
			print(e)
			sys.exit(1)
	colorspace = str(formatinfo.get("colorspace", "default"))
	codec= str(formatinfo.get("codec", "apcs"))
	# newoutputname = os.path.splitext(filename)[0].strip('#')
	newoutputname = re.sub(".{1}####", "", filename)
	newext = formatinfo["ext"]
	fileSuffix = formatinfo.get('file_suffix', '')
	newoutput = "/".join([
		formatoutputpath,
		newoutputname + fileSuffix
	])
	nodeout["colorspace"].setValue(colorspace)
	# Sort of hacky but just check if the extension is jpg
	# if so, add a frame token and change the jpeg quality.
	if newext == ".jpg":
		nodeout["file_type"].setValue(str(newext).strip('.'))
		nodeout['_jpeg_quality'].setValue(1.0)
		newoutput = newoutput + ".####" + newext
	elif newext == ".mov":
		# Set the mov to an sRGB space and Apple Pro Res 422 LT
		nodeout["file_type"].setValue(str(newext).strip('.'))
		# TODO Extract from the codec
		nodeout["meta_codec"].setValue(codec)
		# Set a pixelFormat on the output node, only applicable to certain codecs
		# so we'll test to make sure the knob exists before trying to set it.
		pixFmt = formatinfo.get('pixelFormat', 0)
		if pixFmt and nodeout.knob('mov32_pixel_format'):
			nodeout['mov32_pixel_format'].setValue(pixFmt)
		newoutput = newoutput + newext
	else:
		nodeout["file_type"].setValue(str(newext).strip('.'))
		newoutput = newoutput + ".####" + newext
	nodeout["file"].setValue(newoutput)
	# Jpeg isn't an option until after you set it
	return newoutput

def addTimeCode(formatinfo, frame):
	timeCodeNodeName = formatinfo.get('timecode')
	if timeCodeNodeName:
		timeCodeNode = nuke.toNode(timeCodeNodeName)
		if timeCodeNode:
			timeCodeNode["useFrame"].setValue(True)
			timeCodeNode["frame"].setValue(frame)

def getBlastBackupNukeDir(projectname, shotname=None, assetname=None):
	assetTypeName = None
	element = None
	# Determine whether we are using a shot or asset, then build our
	# query based off that.
	if shotname:
		shotgroup, shotstr = shotname.split("_")
		element = trax.api.findShot(shotstr, shotgroup, projectname)
		assetTypeName = "Shot"
	elif assetname:
		element = trax.api.findAsset(assetname, projectname)
		assetTypeName = "Asset"
	else:
		# There is no shot or asset defined.  Store in users local dir
		blastBackupDir = "C:/temp/BlastBackup"

	if element:
		aType = trax.api.data.AssetType.recordByName(assetTypeName)
		fType = trax.api.data.FileType.recordByAssetTypeAndId(aType, "BlastBackup")
		blastBackupDir = fType.fullPath(element)
	if not os.path.exists(blastBackupDir):
		os.makedirs(blastBackupDir)
	return blastBackupDir

def getBlastBackupNukePath(blastOptions, formatname):
	"""
	Retrieve the path of the blast backup

	Args:
		blastOptions(dict) : Dictionary of blast options
	"""
	kwargs = {'projectname' : blastOptions.project}
	nukeTag = ""
	if blastOptions.shot:
		kwargs['shotname'] = blastOptions.shot
		nukeTag = blastOptions.shot
	if blastOptions.asset:
		kwargs['assetname'] = blastOptions.asset
		nukeTag = blastOptions.asset
	blastBackupDir = getBlastBackupNukeDir(**kwargs)
	# Retrieve the artists name
	tEmployee = trax.api.data.Employee.recordByDisplayName(blastOptions.artist)
	usertag = ""
	if tEmployee.isRecord():
		usertag = str(tEmployee.username())
	# Append a datetime to track when it was created
	datestr = datetime.now().strftime("%m_%d_%y_%H_%M")
	basename = "{0}_{1}_{2}_{3}.nk".format(
		nukeTag,
		usertag,
		datestr,
		formatname
	)
	blastBackupPath = os.path.join(blastBackupDir, basename)
	return blastBackupPath

def getCCCFromCDL(cdlPath):
	cdlId = ""
	cdlTree = ET.parse(cdlPath)
	cdlRoot = cdlTree.getroot()
	elementName = '{urn:ASC:CDL:v1.01}ColorCorrection'
	element = cdlRoot.find(elementName)
	if element:
		cdlId = element.attrib['id']
	return cdlId

def setCDL(formatinfo, project, shot):
	# if not project or not shot:
	# 	return
	cdlName = formatinfo.get('cdl_node')
	sg = blursg.sg()
	sgProject = sg.find_one("Project", [["name", "is", project]], [])
	sgShot = sg.find_one("Shot", [["project", "is", sgProject], ["code", "is", shot]])
	cdl = sg.find_one(
		"Version",
		[
			['entity', 'is', sgShot],
			['sg_status_list', 'is', 'apr'],
			['sg_version_type', 'is', 'cdl']
		],
		['sg_path_to_movie']
	)
	if cdlName and cdl:
		cdlNode = nuke.toNode(cdlName)
		if cdlNode:
			normalizedCDLPath = cdl['sg_path_to_movie'].replace("\\", "/")
			cccid = getCCCFromCDL(normalizedCDLPath)
			print "CCCID is {0}".format(cccid)
			cdlNode["file"].setValue(normalizedCDLPath)
			cdlNode["cccid"].setValue(cccid)
			cdlNode["reload"].execute()


def set3DL(formatinfo, project, shot):
	# if not project or not shot:
	# 	return
	lutName = formatinfo.get('lut_node')
	sg = blursg.sg()
	sgProject = sg.find_one("Project", [["name", "is", project]], [])
	sgShot = sg.find_one("Shot", [["project", "is", sgProject], ["code", "is", shot]])
	lut = sg.find_one(
		"Version",
		[["entity", "is", sgShot], ["sg_version_type", "is", "3dl"], ["sg_variation", "is", "3DL"]],
		['sg_path_to_movie'],
		[{'field_name': 'sg_version_number', 'direction' : 'desc'}]
	)
	if lutName and lut:
		normalizedLutPath = lut['sg_path_to_movie'].replace("\\", "/")
		lutNode = nuke.toNode(lutName)
		if lutNode:
			lutNode["vfield_file"].setValue(normalizedLutPath)

def setCDLSwitch(formatinfo):
	if formatinfo.get('cdlswitch'):
		node = nuke.toNode(formatinfo.get('cdlswitch'))
		if node:
			node['which'].setValue(1)

def setFramerate(project):
	proj = trax.api.data.Project.recordByName(project)
	fps = proj.primaryOutput().fps()
	nuke.Root().knob('fps').setValue(fps)

def setLUTSwitch(formatinfo):
	if formatinfo.get('lutswitch'):
		node = nuke.toNode(formatinfo.get('lutswitch'))
		if node:
			node['which'].setValue(1)

def importPlate(project, shot, nodeName, fileType="Flat Plate", variation=""):
	# if not project or not shot:
	# 	return
	sg = blursg.sg()
	sgProject = sg.find_one("Project", [["name", "is", project]], [])
	sgShot = sg.find_one("Shot", [["project", "is", sgProject], ["code", "is", shot]])
	sgFilter = [
		["entity", "is", sgShot],
		["sg_version_type", "is", fileType],
	]
	plate = sg.find_one(
		"Version",
		sgFilter,
		['sg_path_to_frames'],
		[{'field_name': 'sg_version_number', 'direction' : 'desc'}]
	)
	if plate:
		pathToFrames = plate['sg_path_to_frames'].replace("\\", "/")
		plateNode = nuke.toNode(nodeName)
		if plateNode:
			plateNode["file"].setValue(pathToFrames)

def main():
	blastOptions = parseArgs()
	print blastOptions.comp
	openComp(blastOptions.comp)
	formatsdata = None
	# Retrieve the formats presets
	with open(blastOptions.formatsfile, "r") as formatfile:
		formatsdata = formatfile.read()
	# set the framerate to the project framerate
	setFramerate(blastOptions.project)
	formatjson = json.loads(formatsdata)
	for formatname in blastOptions.formats:
		formatinfo = formatjson[formatname]
		nodeinName = formatinfo["nodes"][0]
		nodeout = formatinfo["nodes"][1]
		inputfilename = os.path.basename(blastOptions.file)
		print "NODE IN IS {0}".format(nodeinName)
		print "NODE OUT IS {0}".format(nodeout)
		# Ensure the input node is correct
		nodein = nuke.toNode(nodeinName)
		if not nodein:
			print "Input node is incorrect: {0}".format(nodeinName)
			sys.exit(1)
		# Set the input nodes image sequence
		setImageSequence(blastOptions.file, nodein)

		# If there is plate importing required, do it here
		if formatinfo.get("import_flattened_plate"):
			plateNodeName = formatinfo["import_flattened_plate"]
			importPlate(blastOptions.project, blastOptions.shot, plateNodeName)
		# If there is no extension specified, take the extension of the input
		if not formatinfo.get("ext", None):
			formatinfo["ext"] = os.path.splitext(nodein['file'].value())[1]
		framein, frameout = getFrameRange(formatinfo, blastOptions, nodeinName, nodeout)
		increment = 1
		# If first/middle/last specified, handle getting those frames
		if formatinfo.get('fml'):
			increment = (int(frameout) - int(framein)) // 2
		# If specified by preferences, set the colorspace to the input
		if formatinfo.get("overrideJpegColorspace"):
			bitsPerChannel = nodein.metadata()['input/bitsperchannel']
			if bitsPerChannel == "8-bit fixed":
				overrideColorSpace = str(formatinfo.get("overrideJpegColorspace"))
				nodein['colorspace'].setValue(overrideColorSpace)
        # If this is a slate frame, make a temporary store the actual frame number
		slateFrameOut = 0
		# Make sure the pad the frames by 1 to account for slate
		if blastOptions.createSlate and formatinfo.get("slate_node"):
			framein = framein - 1
		if formatinfo.get('single_frame'):
			framein = 1000
			slateFrameOut = blastOptions.frameout
			frameout = framein
		# Set the project frame range
		nuke.Root()['first_frame'].setValue(framein)
		nuke.Root()['last_frame'].setValue(frameout)
		# Set the key on the slate to put it at the beginning
		if blastOptions.createSlate:
			keySlate(formatinfo, framein)
		# Fill out the information for the burnin
		editBurnin(blastOptions, formatinfo)
		slateFrameIn = framein
		if not slateFrameOut:
			slateFrameOut = frameout
		editSlate(blastOptions, formatinfo, slateFrameIn, slateFrameOut)
		nukeNodeOut = nuke.toNode(nodeout)
		outputfilepath = setOutputNode(
			nukeNodeOut,
			blastOptions,
			formatinfo,
			blastOptions.filename
		)
		print "Frame in is {0}. Frame out is {1}".format(framein, frameout)
		# Set the time code for one frame afterwards
		addTimeCode(formatinfo, framein)

		# These options are shot dependent and therefore require a shot.
		audioFile = None
		if blastOptions.shot:
			# Avoid color if option is set
			if blastOptions.nolut or 'blursg' not in sys.modules.keys():
				setLUTSwitch(formatinfo)
			if blastOptions.nocdl or 'blursg' not in sys.modules.keys():
				setCDLSwitch(formatinfo)

			# Apply postmove
			if blastOptions.applyPostmove:
				applyPostmove(formatinfo, blastOptions.project, blastOptions.shot, nodein)

			# If a postmove is applied, we can disable apply distortion.
			# However, if apply postmove is specified, this should not change
			# whether the distortion needs to be applied.
			if (not blastOptions.applyPostmove and
					getPostmove(formatinfo, blastOptions.project, blastOptions.shot)):
				blastOptions.applyDistortion = False

			# Apply distortion
			if blastOptions.applyDistortion:
				applyDistortion(formatinfo, blastOptions.project, blastOptions.shot)

			if blastOptions.applyUndistortion:
				applyDistortion(
					formatinfo,
					blastOptions.project,
					blastOptions.shot,
					distort=False
				)
			# Set audio on the output node.
			if not blastOptions.noaudio:
				audioFile = addAudio(nukeNodeOut, blastOptions.project, blastOptions.shot)
			# Set the color information. This is retrieved from the shot data
				if 'blursg' in sys.modules.keys():
					setCDL(formatinfo, blastOptions.project, blastOptions.shot)
					set3DL(formatinfo, blastOptions.project, blastOptions.shot)
		# Testing to see if closing the script and opening again will fix this issue
		shotScriptPath = getBlastBackupNukePath(blastOptions, formatname)
		print "Saving the script"
		nuke.scriptSave(shotScriptPath)
		print "Closing the script"
		nuke.scriptClose()
		print "Reopening the script"
		nuke.scriptOpen(shotScriptPath)
		nukeNodeOut = nuke.toNode(nodeout)
		render(nukeNodeOut, framein, frameout, increment)
		if blastOptions.runffmpeg and formatinfo["ext"] == ".png" and formatinfo.get("runffmpeg"):
			# Create a FileSequence object to generate a movie
			fsFilepath = outputfilepath.replace("####", "%04d")
			if blastOptions.shot:
				elementKwarg = {'shotname' : blastOptions.shot}
			elif blastOptions.asset:
				elementKwarg = {'assetname' : blastOptions.asset}
			else:
				elementKwarg = {}
			runffmpegaction(
				framein,
				str(fsFilepath),
				audioFile,
				blastOptions.project,
				**elementKwarg
			)
			fileSequencePath = outputfilepath.replace(
				"####",
				"{0}-{1}".format(
					str(framein).zfill(4),
					str(frameout).zfill(4)
				)
			)
			# Delete the review image file sequence
			fileSequence = FileSequence(fileSequencePath)
			fileSequence.delete()
			# ffmpegCmd = fileSequence.generateMovie(fps=23.976, videoCodec=VideoCodec(formatinfo['codec']))
		# print ffmpegCmd

	# nuke.scriptSave(blastOptions.comp)
	# TODO Create a backup in a specific shot folder
	nuke.scriptSave("C:/temp/blast_backup.nk")
	sys.exit(0)


if __name__ == "__main__":
	main()
