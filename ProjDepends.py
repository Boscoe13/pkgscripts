#!/usr/bin/python2
# Copyright (c) 2000-2015 Synology Inc. All rights reserved.


import sys, os, glob

# Paths
ScriptDir = os.path.dirname(os.path.abspath(sys.argv[0]))
BaseDir = os.path.dirname(ScriptDir)
ScriptName = os.path.basename(sys.argv[0])

sys.path.append(ScriptDir+'/include')
import pythonutils
from pythonutils import *


def displayUsage(code):
	message = '\nUsage\n\t'+ScriptName
	message += ' [-x|-r{level}] [-p|--platform platform] project+'
	message += """

Synopsis
	Re-order specified projects according to their dependency.

Options
	-x {level}
		Traverse all dependant projects and generate project list in build sequence.
		Can carry level number to specify the traversing level. Give 0 means no limit.
		For example, -x3 means to traverse dependency to 3rd level (itself as level 0).
		Cannot be used with -r.
	-r {level}
		Expand project dependency list reversely. Cannot be used with -x.
	-p, --platform {platform}
		Specify platform.
	-h, --help
		Show this help.
"""
	print >> sys.stderr, message
	sys.exit(code)


def loadDependsFiles(arch):

	# Load basic dependency config file
	filename = ScriptDir+'/include/project.depends'
	dict_var, dict_dep, dict_kernel = readDependsBase(filename)

	# Load SynoBuildConf/depends
	for filename in glob.glob(BaseDir+'/source/*/SynoBuildConf/depends*'):
		proj = filename.split('/')[-3]
		name = filename.split('/')[-1]
		proj_idx = string.find(proj, VIRTUAL_PROJ_SEP)
		file_idx = string.find(name, VIRTUAL_PROJ_SEP)
		if proj_idx != -1: proj = proj[:proj_idx]
		if file_idx != -1: proj += name[file_idx:]
		dict_conf = readDependsConf(filename, arch)

		# Merge config files
		if dict_dep.has_key(proj): reportMessage(ERROR_DEBUG, 'Dependency of '+proj+' is overwritten by '+filename)
		dict_dep[proj] = dict_conf['build']['base']+dict_conf['build']['curr']
		dict_bug = dict_conf['build']['bug']
		for bug in dict_bug:
			if dict_dep.has_key(bug): reportMessage(ERROR_DEBUG, 'Dependency of '+bug+' is overwritten by '+filename)
			if len(dict_bug[bug]) == 0: del dict_dep[bug]  # Don't keep proj without dependent projects
			else: dict_dep[bug] = dict_bug[bug]

	return dict_var, dict_dep, dict_kernel


def resolveDependsDepth(heads, dict_dep, max_depth):
	keep = set(heads)
	todo = keep.copy()
	while len(todo) != 0 and max_depth > 0:
		curr = todo.copy()
		todo.clear()
		for proj in curr:
			if not dict_dep.has_key(proj): continue
			todo |= set(dict_dep[proj])-keep
		keep |= todo
		max_depth -= 1
	return keep

def traverseDependsTree(head, dict_dep, list_result, seen):
	global LogCircularDep
	seen.add(head)
	if not dict_dep.has_key(head):
		list_result.append(head)
		return True
	for proj in dict_dep[head]:
		if proj not in seen:
			if not traverseDependsTree(proj, dict_dep, list_result, seen):
				LogCircularDep = proj+'->'+LogCircularDep
				return False
		elif proj not in list_result:
			LogCircularDep = proj
			return False
	list_result.append(head)
	return True

def traverseDepends(list_proj, dict_dep, max_depth):
	list_result = []
	seen = set()
	for proj in list_proj:
		if proj not in list_result:
			if not traverseDependsTree(proj, dict_dep, list_result, seen):
				reportMessage(ERROR_DEP, 'Circular dependency: '+LogCircularDep)
	if max_depth == 0:
		return list_result
	else:
		list_prune = []
		keep = resolveDependsDepth(list_proj, dict_dep, max_depth)
		for proj in list_result:
			if proj in keep:
				list_prune.append(proj)
		return list_prune

def expandRevDepends(list_proj, dict_dep, max_depth):
	# TODO Necessary to sort result according to dependency?
	no_stop = False
	if max_depth == 0: no_stop = True
	keep = set(list_proj)
	todo = keep.copy()
	while len(todo) != 0 and (max_depth > 0 or no_stop):
		curr = todo.copy()
		todo.clear()
		for proj in curr:
			for key in dict_dep:
				if key not in keep and proj in dict_dep[key]: todo.add(key)
		keep |= todo
		max_depth -= 1
	return keep


def replaceVariables(dict_dep, dict_var):
	for var in dict_var:
		for proj in dict_dep:
			try:
				dict_dep[proj].remove(var)
				dict_dep[proj].extend(dict_var[var].split(' '))
			except: pass
			if proj == var:
				tmp = dict_dep.pop(proj)
				dict_dep[dict_var[var]] = tmp


def replaceKernelProjects(list_proj, dict_kernel, stored):
	try: idx = list_proj.index(VAR_KERNEL_PROJ)
	except: pass
	else:
		if len(Platforms) == 0:
			kernels = set(dict_kernel.values())
			if len(stored) != 0: kernels.intersection_update(stored)
			list_proj[idx] = string.join(kernels, ' ')
		else:
			kernels = set()
			for arch in Platforms: kernels.add(dict_kernel[arch])
			list_proj[idx] = string.join(kernels, ' ')


if __name__ == '__main__':
	TraverseAll = False
	DepthMax = -1
	Mission = ''
	Platforms = ''
	LogCircularDep = ''

	# Parse options
	try:
		DictOpt, ListArg = getopt(sys.argv[1:], 'x:r:p:h', ['base', 'help', 'debug'])
	except GetoptError:
		displayUsage(ERROR_ARG)
	for opt, arg in DictOpt:
		if opt == '-x' or opt == '-r':
			if (arg.isdigit()): DepthMax = int(arg)
			else: reportMessage(ERROR_ARG, 'Invalid level "'+arg+'"')
			if opt == '-r': Mission = 'rdepends'
		if opt == '-p' or opt == '--platform': Platforms = arg.split(' ')
		if opt == '-h' or opt == '--help': displayUsage(ERROR_NONE)
		if opt == '--base': TraverseAll = True  # TODO only when package?
		if opt == '--debug': pythonutils.ENABLE_DEBUG = True

	if len(ListArg) == 0:
		displayUsage(ERROR_NONE)

	# Load dependency config files
	if len(Platforms) == 1:
		DictVar, DictDep, DictKernel = loadDependsFiles(Platforms[0])
	else:
		DictVar, DictDep, DictKernel = loadDependsFiles('')

	# Replace kernel projects and variables
	KernelProjects = set(DictKernel.values()).intersection(ListArg)
	StoredKernel = set()
	if len(KernelProjects) > 0:
		for proj in KernelProjects:
			ListArg.remove(proj)
			StoredKernel.add(proj)
		ListArg.append(VAR_KERNEL_PROJ)
	replaceVariables(DictDep, DictVar)

	# Traverse dependency
	if Mission == 'rdepends':
		ListResult = expandRevDepends(ListArg, DictDep, DepthMax)
	else:
		ListResult = traverseDepends(ListArg, DictDep, DepthMax)
	replaceKernelProjects(ListResult, DictKernel, StoredKernel)
	print string.join(ListResult, ' ')
	sys.exit(ERROR_NONE)
