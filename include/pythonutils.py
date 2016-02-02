#!/usr/bin/python2
# Copyright (c) 2000-2015 Synology Inc. All rights reserved.


import sys, os, string, re
from getopt import getopt, GetoptError
from subprocess import check_call, CalledProcessError, Popen, PIPE
from time import time, ctime


# Error codes
ERROR_NONE = 0
ERROR_DEBUG = 1
ERROR_LOG = 2
ERROR_ARG = 3
ERROR_IO = 4
ERROR_DEP = 5
ERROR_OTHER = 6

# Section names in dependency config files
SECTION_VAR = 'variables'
SECTION_DEP = 'project dependency'
SECTION_KERNEL = 'platform kernel'
BASE_SECTIONS = [SECTION_VAR, SECTION_DEP, SECTION_KERNEL]
SECTION_BUILD = 'BuildDependent'
SECTION_REF = 'ReferenceOnly'
SECTION_PACK = 'PackagePacking'
SECTION_BUG = SECTION_BUILD+'-Bug'
SECTION_DEFAULT = 'default'
CONF_SECTIONS = [SECTION_BUILD, SECTION_BUILD+'-Tag', SECTION_REF, SECTION_REF+'-Tag', SECTION_PACK, SECTION_PACK+'-Tag', SECTION_BUG]

VAR_KERNEL_PROJ = '${KernelProjs}'  # Variable name for kernel project
ENABLE_DEBUG = False  # Debug flag
VIRTUAL_PROJ_SEP = '-virtual-'

# Keys in INFO to be considered
INFO_KEYS = ['package', 'version', 'arch']

# Basic projects to be checkout
BasicProjects = set(['uistring', 'synopkgutils'])


def reportMessage(code, message):
	if code == ERROR_NONE:
		print >> sys.stderr, 'Warning: '+message+'!\n'
	elif code == ERROR_DEBUG:
		if ENABLE_DEBUG: print >> sys.stdout, '\033[34mDebug: '+message+'\033[0m'
	elif code == ERROR_LOG:
		print >> sys.stdout, 'Log: '+message
	else:
		print >> sys.stderr, '\033[31mError: '+message+'!\033[0m\n'
	if code > ERROR_LOG: sys.exit(code)


def getNextLine(file_handle):
	while (True):
		line = file_handle.readline()
		if line == '': break  # EOF
		line = line.strip()
		if line != '' and line[0] != '#': break  # Get non-empty, non-comment line
	return re.sub(r'\s*#.*', '', line)  # Remove comment and return

def parseSectionName(line):
	name = ''
	if re.match(r'\[.*\]', line): name = line[1:len(line)-1]
	return name

def parseKeyValue(line):
	key = ''
	value = []
	if re.match(r'.*\s*=\s*\"', line):
		key = line.split('=')[0].strip()
		value = line.split('"')[1].strip().split(' ')
	return key, value

def parseSectionNames(filename, arch):  # For platform-specific dependency
	sections = []
	for name in CONF_SECTIONS:
		pipe = Popen('grep "^\['+name+':.*'+arch+'.*\]" '+filename, stdout=PIPE, stderr=PIPE, shell=True)
		line = pipe.communicate()[0].strip()
		if pipe.returncode != 0:
			sections.append(name)
			continue
		line = line.split(']')[0]
		if arch in line[string.index(line, ':')+1:].split(','):
			sections.append(line[1:])
		else:
			sections.append(name)
	return sections

def resolveKeyNames(section):
	if re.match(SECTION_BUILD, section): key1 = 'build'
	elif re.match(SECTION_REF, section): key1 = 'ref'
	elif re.match(SECTION_PACK, section): key1 = 'pack'
	else: key1 = ''
	if re.match(r'.*-Tag', section): key2 = 'base'
	elif re.match(r'.*-Bug', section): key2 = 'bug'
	else: key2 = 'curr'
	return key1, key2


def readDependsBase(filename):
	dict_var = {}
	dict_dep = {}
	dict_kernel = {}
	if not os.path.isfile(filename):
		return dict_var, dict_dep, dict_kernel
	try:
		conf = open(filename, 'r')
	except IOError:
		reportMessage(ERROR_IO, 'Fail to open '+filename)
	else:
		section = ''
		while (True):
			line = getNextLine(conf)
			if line == '': break  # EOF
			section_name = parseSectionName(line)
			if section_name != '':
				if section_name not in BASE_SECTIONS: section = ''
				else: section = section_name
				continue
			if section == '': continue
			key, value = parseKeyValue(line)
			if key == '':
				reportMessage(ERROR_IO, "Line '"+line+"' is not a legal key-value pair")
			elif len(value) == 0:
				continue  # Skip line without dependent projects
			elif section == SECTION_VAR:
				dict_var[key] = string.join(value, ' ')
			elif section == SECTION_DEP:
				dict_dep[key] = value
			elif section == SECTION_KERNEL:
				dict_kernel[key] = value[0]
		conf.close()
	return dict_var, dict_dep, dict_kernel


def readDependsConf(filename, arch):
	dict_conf = {'build': {'curr': [], 'base': [], 'bug': {}},
		'ref': {'curr': [], 'base': []},
		'pack': {'curr': [], 'base': []}}
	try:
		conf = open(filename, 'r')
	except IOError:
		reportMessage(ERROR_IO, 'Fail to open '+filename)
	else:
		target_sections = parseSectionNames(filename, arch)
		while (True):
			line = getNextLine(conf)
			if line == '': break  # EOF
			section_name = parseSectionName(line)
			if section_name != '':
				if section_name not in target_sections: key1 = ''
				else: key1, key2 = resolveKeyNames(section_name)
				continue
			if key1 == '':
				continue
			elif key2 == 'bug':
				key, value = parseKeyValue(line)
				if key == '': reportMessage(ERROR_IO, "Line '"+line+"' is not a legal key-value pair")
				else: dict_conf[key1][key2][key] = value
			else:
				dict_conf[key1][key2].append(line)
		conf.close()
	return dict_conf


def getBaseEnvironment(base_dir, proj, env, ver = ""):
	filename = findDependsFile(base_dir, proj)
	dict_env = {}
	if ver:
		dict_env["all"] = ver
		return dict_env

	if not env:
		env = SECTION_DEFAULT

	try:
		conf = open(filename, 'r')
	except IOError:
		reportMessage(ERROR_LOG, 'Fail to open '+filename+'. Assume not a normal project.')
		dict_env['all'] = 'unknown'
	else:
		while (True):
			line = getNextLine(conf)
			if line == '': break  # EOF
			section_name = parseSectionName(line)
			if section_name != '':
				if section_name == env:
					section = env
				else:
					section = ''
				continue
			if section == '':
				continue
			key, value = parseKeyValue(line)
			if key == '':
				reportMessage(ERROR_IO, "Line '"+line+"' is not a legal key-value pair")
			elif len(value) == 0:
				continue  # Skip line without base environment specified
			dict_env[key] = value[0]
		conf.close()
	#if not dict_env.has_key('all'):
	#	reportMessage(ERROR_OTHER, 'Please specify all="..." in '+filename)
	reportMessage(ERROR_LOG, 'Use environment settings in ['+ env +']')
	return dict_env


def getBuiltinProjects(script_dir):
	cmd = '. '+script_dir+'/include/env.config; echo $BuiltinProjects'
	reportMessage(ERROR_LOG, cmd)
	pipe = Popen(cmd, stdout=PIPE, shell=True)
	return set(pipe.stdout.read().strip().split(' '))


def readPackageInfo(filename):
	dict_info = {}
	try:
		info = open(filename, 'r')
	except IOError:
		reportMessage(ERROR_IO, 'Fail to open '+filename)
	else:
		while (True):
			line = getNextLine(info)
			if line == '': break  # EOF
			key, value = parseKeyValue(line)
			if key in INFO_KEYS: dict_info[key] = string.join(value, ' ')
		info.close()
	return dict_info


class TraverseHook:
	def __init__(self, arch, branch, base, do_base):
		self.arch = arch
		self.branch = branch
		self.base = base
		self.do_base = do_base
		pass
	def perform(self, config):
		pass

def resolveBaseTarget(arch, dict_env):
	base = ''
	if dict_env.has_key(arch): base = dict_env[arch]
	elif dict_env.has_key('all'): base = dict_env['all']
	else: reportMessage(ERROR_DEP, 'Base environment not specified for '+arch)
	return base

def replaceSingleVariable(group, target, replacement):
	try:
		group.remove(target)
		if replacement != '': group.add(replacement)
	except KeyError: pass

def replaceVariables(group, arch, dict_var, dict_kernel, do_base):
	if VAR_KERNEL_PROJ in group['curr'] | group['base']:
		try:
			kernel = string.join(set(dict_kernel.values()), ' ') if arch == '' else dict_kernel[arch]
		except KeyError:
			kernel = ''
			reportMessage(ERROR_LOG, 'Kernel projects not specified! Skip it.')
		replaceSingleVariable(group['curr'], VAR_KERNEL_PROJ, kernel)
		if do_base: replaceSingleVariable(group['base'], VAR_KERNEL_PROJ, kernel)
	for key in dict_var.keys():
		replaceSingleVariable(group['curr'], key, dict_var[key])
		if do_base: replaceSingleVariable(group['base'], key, dict_var[key])

def traverseSource(projects, base_dir, arch, dict_info, hook, do_base):
	dict_dep = dict_info['dep']

	seen = {'curr': projects.copy()|BasicProjects, 'base': set()}
	build_dep = {'curr': set(), 'base': set()}
	ref_only = {'curr': set(), 'base': set()}
	for_pack = {'curr': set(), 'base': set()}
	base = resolveBaseTarget(arch, dict_info['env'])

	builtin = getBuiltinProjects(base_dir+'/pkgscripts')
	todo = projects.copy()
	while len(todo) != 0:
		build_dep['curr'].clear()
		if do_base: build_dep['base'].clear()
		for proj in todo:
			filename = findDependsFile(base_dir, proj)
			if not re.match(r'^\$', proj) and os.path.isfile(filename):
				dict_conf = readDependsConf(filename, arch)
				# FIXME merge dict_dep and dict_conf with logs?
				for p in dict_conf['build']['bug']:
					dict_dep[p] = dict_conf['build']['bug'][p];
					if len(dict_dep[p]) == 0 or dict_dep[p][0] == '': del dict_dep[p]
				build_dep['curr'].update(dict_conf['build']['curr'])
				build_dep['curr'].update(dict_conf['pack']['curr'])
				ref_only['curr'].update(dict_conf['ref']['curr'])
				for_pack['curr'].update(dict_conf['pack']['curr'])
				if do_base:
					build_dep['base'].update(dict_conf['build']['base'])
					build_dep['base'].update(dict_conf['pack']['base'])
					ref_only['base'].update(dict_conf['ref']['base'])
					for_pack['curr'].update(dict_conf['pack']['base'])
			elif do_base and dict_dep.has_key(proj):
				build_dep['base'].update(dict_dep[proj])
		build_dep['curr'] -= seen['curr']
		seen['curr'] |= build_dep['curr']
		if do_base:
			build_dep['base'] -= seen['base']
			seen['base'] |= build_dep['base']
			# FIXME better error report?
			conflict = seen['curr'] & seen['base']
			if len(conflict) != 0:
				# Ignore conflict but built-in projects
				level = ERROR_LOG if len(conflict-builtin) == 0 else ERROR_DEP
				reportMessage(level, 'Conflict at {'+string.join(conflict, ',')+'}')

		if hook != None:
			config = {'proj':
					{'curr': build_dep['curr'],
					'base': build_dep['base']},
				'base': base, 'do_base': do_base, 'branch': ''}
			hook.perform(config)

		todo.clear()
		todo.update(build_dep['curr'])
		if do_base: todo.update(build_dep['base'])

	if hook != None:
		config = {'proj':
				{'curr': ref_only['curr'] - seen['curr'],
				'base': ref_only['base'] - seen['base']},
			'base': base, 'do_base': do_base, 'branch': ''}
		try:
			if VAR_KERNEL_PROJ in seen['curr']:
				config['proj']['curr'].add(dict_info['kernel'][arch])
			elif VAR_KERNEL_PROJ in seen['base']:
				config['proj']['base'].add(dict_info['kernel'][arch])
		except KeyError:
			reportMessage(ERROR_LOG, 'Kernel projects not specified! Skip it.')
		hook.perform(config)

	# Replace variables
	for group in [seen, ref_only, for_pack]:
		replaceVariables(group, arch, dict_info['var'], dict_info['kernel'], do_base)
	return seen, ref_only, for_pack


def checkBuildMachine(filename):
	return False


def showTimeCost(start, end, tag):
	diff = int(end-start)
	diff_second = diff%60
	diff_minute = (diff/60)%60
	diff_hour = (diff/3600)%60
	print('Time cost: {0:02d}:{1:02d}:{2:02d}  [{3:s}]'.format(diff_hour, diff_minute, diff_second, tag))


def getArchDir(arch, dict_env):
        return 'ds.' + arch + '-' + getEnvVer(arch, dict_env)


def getEnvVer(arch, dict_env):
	version = ''

	if dict_env.has_key(arch):
		return dict_env[arch]
	elif dict_env.has_key('all'):
		return dict_env['all']
	else:
		reportMessage(ERROR_ARG, 'Fail to get enviroment version of ' + arch)


def detectPlatforms(root_folder, dict_env):
	platforms = []
	if not os.path.isdir(root_folder):
		reportMessage(ERROR_ARG, root_folder+' is not a folder')
	for folder in os.listdir(root_folder):
		if not os.path.isdir(root_folder+'/'+folder): continue
		if not re.match(r'^ds\.', folder): continue
		parts = string.join(folder.split('.')[1:], '.').split('-')
		if len(parts) != 2 or parts[0] == '' or parts[1] == '': continue
		arch = parts[0]
		suffix = string.join(parts[1:], '-')
		idx = arch if dict_env.has_key(arch) else 'all'
		if not dict_env.has_key(idx): continue
		if dict_env[idx] == suffix: platforms.append(arch)
	if not platforms :
		reportMessage(ERROR_ARG, 'No platform found in '+root_folder)
	return platforms


def replaceVirtualProjects(projects):
	result = set()
	addedBase = set()
	for proj in projects:
		idx = string.find(proj, VIRTUAL_PROJ_SEP)
		baseName = proj[:idx]
		if baseName in addedBase: continue
		addedBase.add(baseName)
		result.add(proj)
	return result

def findDependsFile(base_dir, proj):
	idx = string.find(proj, VIRTUAL_PROJ_SEP)
	if idx == -1:
		real = proj
		suffix = ''
	else:
		real = proj[:idx]
		suffix = proj[idx:]
	filename = base_dir+'/source/'+real+'/SynoBuildConf/depends'
	return filename+suffix if os.path.isfile(filename+suffix) else filename


def setDependsFile(script_dir, arch, dict_env):
	curr_dir = os.getcwd()
	os.chdir(script_dir)
	try: check_call('. include/gitutils; GitSetDependsFile '+arch+':'+resolveBaseTarget(arch, dict_env), shell=True)
	except CalledProcessError: pass
	os.chdir(curr_dir)
