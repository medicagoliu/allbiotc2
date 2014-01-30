#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright 2012,2013 Tobias Marschall and Alexander Schönhuth
# 
# This file is part of CLEVER.
# 
# CLEVER is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# CLEVER is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with CLEVER.  If not, see <http://www.gnu.org/licenses/>.

from __future__ import print_function, division
from optparse import OptionParser, OptionGroup
import sys
import os
import re
from bitarray import bitarray
from collections import defaultdict
import math

__author__ = "Tobias Marschall and Alexander Schönhuth"

usage = """%prog [options] <truth> <predictions0.vcf> [<predictions1.vcf>...<predictionsN.vcf>]

Reads a file with true variations and one (or more) file(s) with predictions and
computes some statistics."""

def index_from_type(genostring):
	
	# 0 = not present, 1 = hetero, 2 = homo

	index = 0
	for i in range(len(genostring)):
		index += 3**i * int(genostring[len(genostring)-i-1])
	return index

def membership_from_type(genostring):
	
	index = 0
	for i in range(len(genostring)):
		index += 2**i * min(int(genostring[len(genostring)-i-1]), 1)
	return index

type2member = [0, 1, 1, 2, 4, 4, 2, 4, 4, 3, 5, 5, 6, 7, 7, 6, 7, 7, 3, 5, 5, 6, 7, 7, 6, 7, 7]
# 0 = not present, 
# 1 = only in child 
# 2 = only in father
# 3 = only in mother, 
# 4 = only in father and child
# 5 = only in mother and child
# 6 = only in mother and father, 
# 7 = in all three

type2trio = [0, 1, 11, 2, 3, 12, 13, 4, 14, 2, 3, 12, 5, 6, 7, 15, 8, 9, 13, 4, 14, 15, 8, 9, 16, 17, 10]
# not distinguishing between parents, but including zygosity
# > 10: mistyped, does not reflect Mendelian genetics
# 0 = not present
# 1, 11 = only child, 
# 2, 13 = only one parent
# 3, 4, 12, 14 = one parent and child
# 5, 15, 16 = both parents, not in child
# 6, 7, 8, 9, 10, 17 = all three family members
# see triotypedict, mistypedict

triotypedict = {'000':0, '001':1, '010':2, '100':2 , '011':3, '101':3 , '021':4, '201':4, '110':5 , '111':6, '112':7 ,'121':8, '211':8, '122':9, '212':9, '222':10}
mistypedict = {'002':11, '012':12, '102':12, '020':13, '200':13, '022':14, '202':14, '120':15, '210':15, '220':16, '221':17}
#alltypedict = triotypedict + mistypedict

typedict = {'000':0, '001':1, '002':2, '010':3, '011':4, '012':5, '020':6, '021':7, '022':8, '100':9 , '101':10, '102':11, '110':12, '111':13, '112':14, '120':15, '121':16, '122':17, '200':18, '201':19, '202':20, '210': 21, '211':22, '212':23, '220':24, '221':25, '222':26}
mistypes = [2,5,6,8,11,15,18,20,21,24,25]

class VariationStatistics:
	"""Statistics for one variation."""
	def __init__(self, chromosome, index, typing=None):
		self.chromosome = chromosome
		self.index = index
		self.typing = typing
		# List of (similar) annotations of same type, i.e. insertion/deletion: (index,length_diff,offset,genotype)
		self.hits = []
		# List of hits to events of type MIX: (index,length_diff,offset,genotype)
		self.mix_hits = []
	def add_hit(self, index, length_diff, offset, typing=None, mix_hit=False):
		#print('add_hit',index, length_diff, offset, typing, mix_hit, file=sys.stderr)
		if mix_hit:
			self.mix_hits.append((index,length_diff,offset,typing))
		else:
			self.hits.append((index,length_diff,offset,typing))
	def is_hit(self):
		return len(self.hits) > 0
	def get_best_hit(self):
		if len(self.hits) == 0:
			return None, None, None
		best_score = float('inf')
		best_index = -1
		for i, (index, length_diff, offset, typing) in enumerate(self.hits):
			score = max(length_diff, offset)
			if score < best_score:
				best_score = score
				best_index = i
		return self.hits[best_index]
	def is_mix_hit(self):
		return len(self.mix_hits) > 0

def nonemax(v1, v2):
	"""None-aware version of max."""
	if v1 == None: return v2
	if v2 == None: return v1
	if math.isnan(v1): return v2
	if math.isnan(v2): return v1
	return max(v1,v2)

def nonemin(v1, v2):
	"""None-aware version of min."""
	if v1 == None: return v2
	if v2 == None: return v1
	if math.isnan(v1): return v2
	if math.isnan(v2): return v1
	return min(v1,v2)

allowed_dna_chars = set(['A','C','G','T','R','Y','M','K','W','S','B','D','H','V','N','a','c','g','t','r','y','m','k','w','s','b','d','h','v','n'])

def valid_dna_string(s):
	chars = set(c for c in s)
	return chars.issubset(allowed_dna_chars)

class ToolStatistics:
	"""Statistics for one tool."""
	def __init__(self, name = None):
		self.name = name
		self.insertion_count = None
		self.insertion_recall = None
		self.insertion_precision = None
		self.insertion_mix_hits = None
		self.insertion_exclusivity = None
		self.insertion_avg_lendiff = None
		self.insertion_avg_distance = None
		self.insertion_f = None
		self.insertion_precision_types = None
		self.insertion_precision_varsums = None
		self.insertion_precision_callsums = None
		self.insertion_recall_types = None
		self.insertion_recall_varsums = None
		self.insertion_recall_callsums = None
		self.deletion_count = None
		self.deletion_recall = None
		self.deletion_precision = None
		self.deletion_mix_hits = None
		self.deletion_exclusivity = None
		self.deletion_avg_lendiff = None
		self.deletion_avg_distance = None
		self.deletion_f = None
		self.deletion_precision_types = None
		self.deletion_precision_varsums = None
		self.deletion_precision_callsums = None
		self.deletion_recall_types = None
		self.deletion_recall_varsums = None
		self.deletion_recall_callsums = None
	def improve(self, results):
		"""Compares itself to some other Results and changes values to the best of both."""
		self.name = None
		self.insertion_recall = nonemax(self.insertion_recall, results.insertion_recall)
		self.insertion_precision = nonemax(self.insertion_precision, results.insertion_precision)
		self.insertion_mix_hits = nonemax(self.insertion_mix_hits, results.insertion_mix_hits)
		self.insertion_exclusivity = nonemax(self.insertion_exclusivity, results.insertion_exclusivity)
		self.insertion_avg_lendiff = nonemin(self.insertion_avg_lendiff, results.insertion_avg_lendiff)
		self.insertion_avg_distance = nonemin(self.insertion_avg_distance, results.insertion_avg_distance)
		self.insertion_f = nonemax(self.insertion_f, results.insertion_f)
		self.deletion_recall = nonemax(self.deletion_recall, results.deletion_recall)
		self.deletion_precision = nonemax(self.deletion_precision, results.deletion_precision)
		self.deletion_mix_hits = nonemax(self.deletion_mix_hits, results.deletion_mix_hits)
		self.deletion_exclusivity = nonemax(self.deletion_exclusivity, results.deletion_exclusivity)
		self.deletion_avg_lendiff = nonemin(self.deletion_avg_lendiff, results.deletion_avg_lendiff)
		self.deletion_avg_distance = nonemin(self.deletion_avg_distance, results.deletion_avg_distance)
		self.deletion_f = nonemax(self.deletion_f, results.deletion_f)

class VariationList:
	"""
		Essentially we read in a VCF. Support for versions upto 4.1
	"""
	def __init__(self,filename,istrio=False):

		self.variations = defaultdict(list)

		n = 0
		header = None
		header_dict = None
		for line in (s.strip() for s in file(filename)):
			n += 1
			if line.startswith('##'): continue
			if line.startswith('#'):
				header = line[1:].split()
				header_dict = dict((name.lower(),index) for index,name in enumerate(header))
				if istrio:
					if (not header_dict.has_key('mother')) or (not header_dict.has_key('father')) or (not header_dict.has_key('child')):
						print('Expecting sample names "mother", "father", and "child" when in trio mode.', file=sys.stderr)
						sys.exit(1)
				continue
			fields = line.split()
			ref = fields[3]
			alt = fields[4]
			
			info_fields = dict(s.split('=') for s in fields[7].strip(';').split(';') if '=' in s)


			event_types = {
				'tandem': "DUP:TANDEM",
				'del': "DEL",
				'invers': "INV",
				'del_ins': "INS", # deletion with insertion at breakpoint 
				'transl': "TRANS", # not official spec, not used in this script
			}
			if self.probeVCFversion( line ) >= (4,1,0):
				# map some fields from 4.1 spec to 4.0
				if info_fields['SVTYPE'] == 'BND':
					event_type = info_fields['EVENT'].split("_")[0].lower() # e.g. del_5468 > DEL
					# special case #(del_ins)
					# if the event is not known (yet), set unknown
					event = event_types.get( event_type, "unk" )
					info_fields['SVTYPE'] = event
					
					# alter the chrB, populate with information from ALT
					# format: [chrB:posB[
#					print(re.findall(r'([\w\d]+)\:([\d]+)', alt, re.I | re.M))
					
					
				if info_fields['SVTYPE'] in ['DEL', 'INS','del','ins']:
					chrB, posB = re.findall(r'([\w\d]+)\:([\d]+)', alt, re.I | re.M)[0]
					sv_coords = [int(fields[1]), int(posB)]
					sv_coords.sort()
					svlen = sv_coords[1] - sv_coords[0]
					info_fields['SVLEN'] = svlen
					pass
				alt = '.'
				ref = '.'
			if (alt == '.') or (ref == '.'):
				if not 'SVTYPE' in info_fields: continue
				if not 'SVLEN' in info_fields: continue
				if info_fields['SVTYPE'] == 'DEL':
					vartype = 'DEL'
					svlen = abs(int(info_fields['SVLEN']))
					coord1 = int(fields[1]) - 1
					coord2 = coord1 + svlen
					coord3 = None
				elif info_fields['SVTYPE'] == 'INS':
					vartype = 'INS'
					svlen = abs(int(info_fields['SVLEN']))
					coord1 = int(fields[1]) - 1
					coord2 = svlen
					coord3 = None
				elif info_fields['SVTYPE'] == 'MIX':
					assert False, 'Encountered SVTYPE=MIX without explicit sequences'
				else:
					continue
			else:
				if (not valid_dna_string(ref)) or (not valid_dna_string(alt)):
					continue
				if (len(ref) > 1) and (len(alt) == 1):
					vartype = 'DEL'
					svlen = len(ref) - 1
					coord1 = int(fields[1])
					coord2 = coord1 + svlen
					coord3 = None
				elif (len(ref) == 1) and (len(alt) > 1):
					vartype = 'INS'
					svlen = len(alt) - 1
					coord1 = int(fields[1])
					coord2 = svlen
					coord3 = None
				elif (len(ref) > 1) and (len(alt) > 1):
					vartype = 'MIX'
					del_len = len(ref) - 1
					ins_len = len(alt) - 1
					coord1 = int(fields[1])
					coord2 = coord1 + del_len
					coord3 = ins_len
				else:
					continue
			if not fields[0][:3] == 'chr':
				chromosome = 'chr' + fields[0]
			else:
				chromosome = fields[0].lower()
			genotype = None
			if istrio: 
				# if vcf relates to a trio, determine
				# the genotypes of the call/annotation
				format_dict = dict((name,i) for i, name in enumerate(fields[8].split(':')))
				family = [
					fields[header_dict['mother']].split(':')[format_dict['GT']],
					fields[header_dict['father']].split(':')[format_dict['GT']],
					fields[header_dict['child']].split(':')[format_dict['GT']]
				]
				genotype = ''
				for member in family:
					if member in ['1/1', '1|1']:
						genotype += '2'
					elif member in ['1/.', '1/0', '1|0', '1|.', '0|1', '.|1', '0/1', './1']:
						genotype += '1'
					else:
						genotype += '0'
				if genotype == '000': continue
#				typing = alltypedict[genotype]
			# Meaning of coordinate values (coord1, coord2, coord3) for different event types
			# DEL: start, end, none
			# INS: pos, length, none
			# MIX: del_start, del_end, ins_length
			self.variations[chromosome].append((coord1, coord2, coord3, vartype, genotype))

	def probeVCFversion(self, line):
		# Detect VCF version, do not rely on header since this could be a faulty template.
		fields = line.split('\t')
		alt = fields[4]
		# the 4.1+ versions contain []-brackets in the ALT field to denote the breakpoint mates
		if re.findall(r'(\[|\])+', alt, re.I | re.M ):
			# This is version 4.1+
			return (4,1,0)
		else:
			return (4,0,0)

	def get(self, chromosome, index):
		"""Returns coordinates (coord1, coord2, var_type) for the variation with given index."""
		chromosome = chromosome.lower()
		coord1, coord2, coord3, var_type, tags = self.variations[chromosome][index]
		if not tags or len(tags) == 0:
			tags = set([None])
		return coord1, coord2, coord3, var_type, tags
	def get_deletion_bitarray(self, chromosome, chromosome_length, min_length=None, max_length=None):
		"""Returns a bitarray where all deleted positions are set to one."""
		chromosome = chromosome.lower()
		b = bitarray(chromosome_length)
		b.setall(0)
		for start, end, no_coord, var_type, tags in self.variations[chromosome]:
			if var_type != 'DEL': continue
			length = end-start
			if (min_length != None) and (length < min_length): continue
			if (max_length != None) and (length > max_length): continue
			b[start:end] = True
		return b
	def find_all_deletion_overlaps(self, another_list, chromosome, trio=False, min_length=None, max_length=None, offset=0, difflength=0, tag=None):
		"""Returns a dictionary that maps each variation index
		of this list to a set of indices of overlapping
		variations in the given list.

		Returns results where results[index] is a set of indices
		referring to variants in another_list, which 'overlap'
		the variant in self referring to index 'index'. 
		"""
		if difflength == None: difflength = 0
		if offset == None: offset = 0
		chromosome = chromosome.lower()
		events = []
		for n, (coord1, coord2, coord3, var_type, tags) in enumerate(self.variations[chromosome]):
			if var_type != 'DEL': continue
			if (tag!=None) and (not tag in tags) and not trio: continue
			assert coord1 <= coord2
			length = coord2-coord1
			if (min_length != None) and (length < min_length): continue
			if (max_length != None) and (length > max_length): continue
			events.append((coord1, 'S', 0, n))
			events.append((coord2, 'E', 0, n))
		for n, (coord1, coord2, coord3, var_type, tags) in enumerate(another_list.variations[chromosome]):
			if var_type == 'DEL':
				assert coord1 <= coord2
				length = coord2-coord1
				if difflength == None: difflength = 0
				if (min_length != None) and (length < max(min_length - difflength,5)): continue
				if (max_length != None) and (length > max_length + difflength): continue
				events.append((coord1-offset, 'S', 1, n))
				events.append((coord2+offset, 'E', 1, n))
				#events.appcoord2(((coord2 + coord1)/2), 1, n))
			elif var_type == 'MIX':
				assert coord1 <= coord2
				del_length = coord2 - coord1
				ins_length = coord3
				length = del_length - ins_length
				if difflength == None: difflength = 0
				if (min_length != None) and (length < max(min_length - difflength,5)): continue
				if (max_length != None) and (length > max_length + difflength): continue
				events.append((coord1-offset, 'S', 1, n))
				events.append((coord2+offset, 'E', 1, n))
			else:
				continue
		events.sort()
		results = defaultdict(set)
		active = [set(), set()]
		for pos, event_type, list_idx, variation_index in events:
			if event_type == 'S':
				if list_idx == 0:
					for index1 in active[1]:
						results[variation_index].add(index1)
				else: 
					for index0 in active[0]:
						results[index0].add(variation_index)
				active[list_idx].add(variation_index)
			else:
				active[list_idx].remove(variation_index)
		return results

	def find_all_deletion_centerpoint_hits(self, another_list, chromosome, min_length=None, max_length=None, offset=0, difflength=0, tag=None):
		"""Returns a dictionary that maps each variation index
		of this list to a set of indices of close (in terms of
		distance of centerpoints) variations in the given
		list.

		Returns results where results[index] is a set of
		indices referring to variants in another_list, which
		are 'close' to the variant in self referring to index
		'index'.
		"""
		if difflength == None: difflength = 0
		if offset == None: offset = 0
		chromosome = chromosome.lower()
		events = []

		for n, (start, end, no_coord, var_type, tags) in enumerate(self.variations[chromosome]):
			if var_type != 'DEL': continue
			if (tag!=None) and (not tag in tags): continue
			assert start < end
			length = end-start
			centerpoint = (start+end)/2
			if (min_length != None) and (length < min_length): continue
			if (max_length != None) and (length > max_length): continue
			events.append((centerpoint-offset/2, 'S', 0, n))
			events.append((centerpoint+offset/2, 'E', 0, n))	  

		for n, (start, end, no_coord, var_type, tags) in enumerate(another_list.variations[chromosome]):
			if var_type != 'DEL': continue
			assert start < end
			length = end-start
			centerpoint = (start+end)/2
			if difflength == None: difflength = 0
			if (min_length != None) and (length < max(min_length - difflength,5)): continue
			if (max_length != None) and (length > max_length + difflength): continue
			events.append((centerpoint-offset/2, 'S', 1, n))
			events.append((centerpoint+offset/2, 'E', 1, n))
			
		events.sort()
		results = defaultdict(set)
		active = [set(), set()] 

		# events is a list of tuples
		for pos, event_type, list_idx, variation_index in events:
			# if event_type is StartingPosition
			if event_type == 'S':
				if list_idx == 0:
					# only from reference list
					for index1 in active[1]:
						results[variation_index].add(index1)
				else: 
					for index0 in active[0]:
						results[index0].add(variation_index)
				active[list_idx].add(variation_index)
			else: # event_type == 'E': variation_index becomes inactive
				active[list_idx].remove(variation_index)

		return results

	def deletion_hit_statistics(self, another_list, chromosomes, count_stats, mode='overlap', trio=False, min_length=None, max_length=None, offset=0, difflength=0, siglevel=0.0, tag=None):
		stats_list = []
		varnumber = 0
		for chromosome in (x.lower() for x in chromosomes):
			overlaps = self.find_all_deletion_overlaps(another_list, chromosome, trio, min_length, max_length, offset, difflength, tag)
			for i, (event0_coord1, event0_coord2, event0_coord3, var_type0, tags0) in enumerate(self.variations[chromosome]):
				if var_type0 != 'DEL': continue
				del_length0 = event0_coord2 - event0_coord1
				if (min_length != None) and (del_length0 < min_length): continue
				if (max_length != None) and (del_length0 > max_length): continue
				varnumber += 1
				if trio: 
#					print(tags0)
					typing0 = index_from_type(tags0)
				else:
					typing0 = None
				if (tag!=None) and (not tag in tags0) and not trio: continue
				center0 = (event0_coord1 + event0_coord2) / 2
				stats = VariationStatistics(chromosome, i, typing0)
				for j in overlaps[i]:
					event1_coord1, event1_coord2, event1_coord3, var_type1, tags1 = another_list.variations[chromosome][j]
					if trio:
						typing1 = index_from_type(tags1)
					else:
						typing1 = None
					del_length1 = event1_coord2 - event1_coord1
					if var_type1 == "DEL":
						effective_length1 = del_length1
					elif var_type1 == "MIX":
						ins_length1 = event1_coord3
						effective_length1 = del_length1 - ins_length1
					else:
						assert False
					center1 = (event1_coord1 + event1_coord2) / 2
					overlap = max(0, min(event0_coord2,event1_coord2) - max(event0_coord1,event1_coord1))
					if mode == 'overlap':
						if (abs(del_length0-effective_length1) <= difflength) and (overlap > 0):
							stats.add_hit(j, abs(del_length0 - effective_length1), abs(center0 - center1), typing1, var_type1 == 'MIX')
					elif mode == 'fixed_distance':
						if (abs(del_length0-effective_length1) <= difflength) and (abs(center0-center1) <= offset):
							stats.add_hit(j, abs(del_length0 - effective_length1), abs(center0 - center1), typing1, var_type1 == 'MIX')
					elif mode == 'significant':
						assert 0.0 < siglevel < 1.0
						sig = callsignificance(del_length0, abs(center0-center1), abs(del_length0-effective_length1), chromosome, count_stats) 
						if (sig <= siglevel):
							stats.add_hit(j, abs(del_length0 - effective_length1), abs(center0 - center1), typing1, var_type1 == 'MIX')
					else:
						print("Error: invalid mode \"%s\"."%mode, file=sys.stderr)
						sys.exit(1)
				stats_list.append(stats)
#		print(varnumber,len(stats_list),file=sys.stderr)
		return stats_list

	def get_chromosomes(self):
		return self.variations.keys()
	def insertion_distances(self, another_list, chromosome, trio=False, min_length=None, max_length=None, offset=None, difflength=None, tag=None):
		if offset == None: offset = 0
		if difflength == None: difflength = 0
		chromosome = chromosome.lower()
		events = []
		lengths = []
		for n, (coord1, coord2, coord3, var_type, tags) in enumerate(self.variations[chromosome]):
			# semantics for insertions...
			pos = coord1
			length = coord2
			if var_type != 'INS': continue
			if (tag!=None) and (not tag in tags) and not trio: continue
			if length <= 0: continue
			if (min_length != None) and (length < min_length): continue
			if (max_length != None) and (length > max_length): continue
			events.append((pos, 'S', 0, n))
			events.append((pos+length, 'E', 0, n))
		for n, (coord1, coord2, coord3, var_type, tags) in enumerate(another_list.variations[chromosome]):
			# semantics for insertions...
			if var_type == 'INS':
				pos = coord1
				ins_length = coord2
				if ins_length <= 0: continue
				if difflength == None: difflength = 0
				if (min_length != None) and (ins_length < max(5, min_length-difflength)): continue
				if (max_length != None) and (ins_length > max_length+difflength): continue
				events.append((pos-offset, 'S', 1, n))
				events.append((pos+ins_length+offset, 'E', 1, n))
			elif var_type == 'MIX':
				assert coord1 <= coord2
				del_length = coord2 - coord1
				ins_length = coord3
				assert ins_length > 0
				assert del_length > 0
				effective_length = ins_length - del_length
				pos = (coord1 + coord2) // 2
				if difflength == None: difflength = 0
				if (min_length != None) and (effective_length < max(5, min_length-difflength)): continue
				if (max_length != None) and (effective_length > max_length+difflength): continue
				events.append((pos-offset, 'S', 1, n))
				events.append((pos+ins_length+offset, 'E', 1, n))
			else:
				continue
		events.sort()
		results = defaultdict(set)
		active = [set(), set()]
		for pos, event_type, list_idx, variation_index in events:
			if event_type == 'S':
				if list_idx == 0:
					for index1 in active[1]:
						results[variation_index].add(index1)
				else: 
					for index0 in active[0]:
						results[index0].add(variation_index)
				active[list_idx].add(variation_index)
			else:
				active[list_idx].remove(variation_index)
		return results
	def insertion_hit_statistics(self, another_list, chromosomes, count_stats, mode='overlap', trio=False, min_length=None, max_length=None, offset=0, difflength=0, siglevel=0.0, tag=None):
		stats_list = []
		for chromosome in (x.lower() for x in chromosomes):
			overlaps = self.insertion_distances(another_list, chromosome, trio, min_length, max_length, offset, difflength, tag)
			for i, (event0_coord1, event0_coord2, event0_coord3, var_type0, tags0) in enumerate(self.variations[chromosome]):
				if var_type0 != 'INS': continue
				if (tag != None) and (not tag in tags0) and not trio: continue
				#print('event0:', i, event0_coord1, event0_coord2, event0_coord3, var_type0, tags0, file=sys.stderr)
				length0 = event0_coord2
				start0 = event0_coord1
				end0 = event0_coord1 + length0
				if (min_length != None) and (length0 < min_length): continue
				if (max_length != None) and (length0 > max_length): continue
				stats = VariationStatistics(chromosome,i)
				for j in overlaps[i]:
					event1_coord1, event1_coord2, event1_coord3, var_type1, tags1 = another_list.variations[chromosome][j]
					if trio:
						typing1 = index_from_type(tags1)
					else:
						typing1 = None
					#print(' --> event1:', event1_coord1, event1_coord2, event1_coord3, var_type1, tags1, file=sys.stderr)
					if var_type1 == 'INS':
						start1 = event1_coord1
						effective_length1 = event1_coord2
					elif var_type1 == 'MIX':
						#continue # TODO TODO TODO
						# set "position" of event to center of deleted part
						start1 = (event1_coord1 + event1_coord2) // 2
						del_length1 = event1_coord2 - event1_coord1
						ins_length1 = event1_coord3
						effective_length1 = ins_length1 - del_length1
					else:
						assert False
					end1 = start1 + effective_length1
					overlap = max(0, min(end0,end1) - max(start0,start1))
					dist = abs(event0_coord1-start1)
					if mode == 'overlap':
						if (overlap > 0) and (abs(length0 - effective_length1) <= difflength):
							stats.add_hit(j, abs(length0 - effective_length1), dist, typing1, var_type1 == 'MIX')
					elif mode == 'fixed_distance':
						if (dist <= offset) and (abs(length0 - effective_length1) <= difflength):
							#print('var_type1 == MIX:', var_type1 == 'MIX', file=sys.stderr)
							stats.add_hit(j, abs(length0 - effective_length1), dist, typing1, var_type1 == 'MIX')
					elif mode == 'significant':
						assert 0.0 < siglevel < 1.0
						sig = callsignificance(length0, dist, abs(length0 - effective_length1), chromosome, count_stats) 
						if (sig <= siglevel):
							stats.add_hit(j, abs(length0 - effective_length1), dist, typing1, var_type1 == 'MIX')
					else:
						print("Error: invalid mode \"%s\"."%mode, file=sys.stderr)
						sys.exit(1)
				stats_list.append(stats)
#		print(len(stats_list),file=sys.stderr)
		return stats_list

	def get_all_tags(self):
		"""Returns all tags found in the given list of VariationStatistics objects."""
		result = set()
		for var_list in self.variations.itervalues():
			for pos, length, var_type, tags in var_list:
				if not tags or len(tags) == 0:
					tags = set([None])
				result.update(tags)
		return result

def format_stats(TP,FP,TN,FN):
	sensitivity = TP / (TP + FN) if (TP + FN)!=0 else float('nan')
	specificity = TN / (FP + TN) if (FP + TN)!=0 else float('nan')
	precision = TP / (TP + FP) if (TP + FP)!=0 else float('nan')
	# Matthew's correlation coefficient
	mcc_denom = math.sqrt((TP+FP)*(TP+FN)*(TN+FP)*(TN+FN))
	mcc = (TP*TN - FP*FN) / mcc_denom if mcc_denom!=0 else float('nan')
	return '%d %d %d %d %f %f %f %f'%(TP,FP,TN,FN,sensitivity,specificity,precision,mcc)

def scatter_hist(data, filename, title, x_label, y_label):
	"""Reads a list of pairs from "data" and plots a combined scatterplot/histogram to the given filename
	(in PDF) format."""
	# adapted from http://matplotlib.sourceforge.net/examples/pylab_examples/scatter_hist.html
	import numpy as np
	import matplotlib.pyplot as plt
	from matplotlib.ticker import NullFormatter
	if (data == None) or (len(data) == 0):
		plt.text(0.03, 0.8, "No data for \"%s\""%title)
		plt.savefig(filename, format='pdf') 
		plt.close()
		return          
	# the random data
	x = [xd for xd,yd in data]
	y = [yd for xd,yd in data]
	nullfmt   = NullFormatter()         # no labels
	# definitions for the axes
	left, width = 0.1, 0.65
	bottom, height = 0.1, 0.65
	bottom_h = left_h = left+width+0.02
	rect_scatter = [left, bottom, width, height]
	rect_histx = [left, bottom_h, width, 0.2]
	rect_histy = [left_h, bottom, 0.2, height]
	# start with a rectangular Figure
	plt.figure(1, figsize=(12,12))
	axScatter = plt.axes(rect_scatter)
	axHistx = plt.axes(rect_histx)
	axHisty = plt.axes(rect_histy)
	axHistx.xaxis.set_major_formatter(nullfmt)
	axHisty.yaxis.set_major_formatter(nullfmt)
	axScatter.scatter(x, y, marker='o', s=1)
	xmin = np.min(x)
	xmax = np.max(x)
	ymin = np.min(y)
	ymax = np.max(y)
	xymax = np.max( [np.max(np.fabs(x)), np.max(np.fabs(y))] )
	#xbinwidth = int((xmax-xmin)/70)
	#ybinwidth = int((ymax-ymin)/70)
	#lim = ( int(xymax/binwidth) + 1) * binwidth
	axScatter.set_xlim( (xmin-0.05*(xmax-xmin), xmax+0.05*(xmax-xmin)) )
	axScatter.set_ylim( (ymin-0.05*(ymax-ymin), ymax+0.05*(ymax-ymin)) )
	axScatter.set_xlabel(x_label)
	axScatter.set_ylabel(y_label)
	#xbins = np.arange(-xmin, xmax + xbinwidth, xbinwidth)
	#ybins = np.arange(-ymin, ymax + ybinwidth, ybinwidth)
	axHistx.hist(x, bins=70)
	axHisty.hist(y, bins=70, orientation='horizontal')
	axHistx.set_title(title)
	for tick in axHisty.xaxis.get_major_ticks():
		tick.label.set_rotation(270)
	axHistx.set_xlim( axScatter.get_xlim() )
	axHisty.set_ylim( axScatter.get_ylim() )
	plt.savefig(filename, format='pdf') 
	plt.close()

def nan_div(a,b):
	"""Division that yields nan when dividing by zero."""
	try:
		return a / b
	except ZeroDivisionError:
		return float('nan')

def f_measure(recall, precision):
	if (recall == None) or (precision == None): return None
	if math.isnan(recall) or math.isnan(precision): return float('nan')
	if recall + precision == 0.0: return float('nan')
	return 2.0 * (recall*precision) / (recall+precision)

def compute_delpair_significance(variants1, variants2, chromosomes, chromosome_lengths, offset=50, difflength=50, tag=None):
	"""
	"""
	
	min_length = None
	max_length = None
	# min_ and max_length make no sense here

	count_stats1 = compute_count_stats(variants1, chromosome_lengths, 0, 'DEL')
	count_stats2 = compute_count_stats(variants2, chromosome_lengths, 0, 'DEL')
	# beware: compute_count_stats' difflength is to be zero, has
	# nothing to do with the other, incoming difflength

	pair_stats = {}
	
	K1, K2 = 0, 0
	for chromosome in (x.lower() for x in chromosomes):
		pair_stats[chromosome] = []
		overlaps = variants1.find_all_deletion_centerpoint_hits(variants2, chromosome, min_length, max_length, offset, difflength, tag)
		
		for i, (start0, end0, no_coord0, var_type0, tags0) in enumerate(variants1.variations[chromosome]):
			if var_type0 != 'DEL': continue
			if (tag!=None) and (not tag in tags0): continue
			length0 = end0 - start0
			centerpoint0 = (start0 + end0)/2
			for j in overlaps[i]:
				K1, K2 = 0, 0
				start1, end1, no_coord1, var_type1, tags1 = variants2.variations[chromosome][j]
				length1 = end1 - start1
				centerpoint1 = (start1 + end1)/2
				if abs(length1-length0) > difflength:
					continue
				for k in range(min(length0,length1), max(length0,length1)+1):
#					print(chromosome, k, count_stats1[chromosome][k], count_stats2[chromosome][k], file=sys.stderr)
					if len(count_stats1[chromosome][k]) == 2:
						K1 += count_stats1[chromosome][k][0]
					if len(count_stats2[chromosome][k]) == 2:
						K2 += count_stats2[chromosome][k][0]
				significance = 1.0 - math.exp(-float(K1*K2*(abs(centerpoint1-centerpoint0)+1))/chromosome_lengths[chromosome])
				#significance = 1.0 - (1.0-((abs(centerpoint1-centerpoint0)+1)/chromosome_lengths[chromosome]))**(K1*K2)

				pair_stats[chromosome].append((i,j,start0,start1,end0,end1,significance))
	
	return pair_stats

def compute_count_stats(variants, chromosome_lengths, difflength=0, var_type=None):
	"""count_stats[chromosome][i][0] is the number of breakpoints
	in chromosome referring to an indel of length i.

	count_stats[chromosome][i][1] is the percentage of nucleotides
	in chromosome which correspond to breakpoints of indels of
	length in [i-difflength,i+difflength]. For difflength = 0 this
	is just the percentage of nucleotides corresponding to
	breakpoints of indels of length i.
	"""
	if difflength == None: difflength = 0

	count_stats = {}

	for chromosome in chromosome_lengths.keys():

		chromosome = chromosome.lower()
#		print(chromosome, chromosome_lengths[chromosome])
		count_stats[chromosome] = defaultdict(list)

		for variant in variants.variations[chromosome]:
			if variant[2] != var_type: continue
			if var_type == 'DEL':
				length = variant[1] - variant[0]
			if var_type == 'INS':
				length = variant[1]
			for i in range(max(0,length - difflength), length + difflength + 1):
				if len(count_stats[chromosome][i]) == 2:
					count_stats[chromosome][i][0] += 1
					count_stats[chromosome][i][1] += 1.0/chromosome_lengths[chromosome]
				else:
					count_stats[chromosome][i] = [1, 1.0/chromosome_lengths[chromosome]]

	return count_stats		
	
def callsignificance(calllength, offset, difflength, chromosome, count_stats):
	ratio = 0.0
	for i in range(max(5,calllength-difflength), calllength+difflength+1): 
		# 5 is for only considering indels of length at least 5
		if len(count_stats[chromosome][i]) == 2:
			ratio += count_stats[chromosome][i][1]
	return 2.0*offset*ratio
#        return expsig(offset, counts, chrlength)

def expsig(offset, counts, chrlength):
	pass

def summarize_variation_stats_list(stats_list):
	"""Input: list of VariationStatistics.
	Output: hit count, hit rate, avg. length diff, avg. distance, hit bitarray."""
	n = len(stats_list)
	hits = 0
	mix_hits = 0
	avg_length_diff = 0.0
	avg_offset = 0.0
	hit_bitarray = bitarray(n)
	hit_bitarray.setall(0)
	typematrix = []
	for i in range(27):
		typematrix.append([])
		for j in range(27):
			typematrix[-1].append(0)
	variantsums = [0]*27
	callsums = [0]*27

	# typematrix[i][j] is number of type-i-variants that are called by type-j-variant,
	# encoding according to global variable alltypes
	# Note: typematrix[0][j] should be zero, for all j (0 encodes no call)
	# Note: typematrix[i][0] is number of type-i-variants that have not been called 
	# Note: variantsums[i] is the sum of type-i-variants
	# Note: callsums[j] is the sum of variants called by type-j-variants
	# Hence: (variantsums[i] - typematrix[i][0]) / variantsums[i] is type-i related recall or precision
	for i, stats in enumerate(stats_list):
		typing0 = stats.typing
		if typing0 != None:
			variantsums[typing0] += 1
		if stats.is_hit():
			index, length_diff, offset, typing1 = stats.get_best_hit()
			#print(typing0, typing1)
			hits += 1
			avg_length_diff += length_diff
			avg_offset += offset
			hit_bitarray[i] = 1
			if typing0 != None and typing1 != None:
				typematrix[typing0][typing1] += 1
				callsums[typing1] += 1
		elif stats.is_mix_hit():
			mix_hits += 1
		else:
			if typing0 != None:
				typematrix[typing0][0] += 1 # false hit: type = '000', not in any family member

	#print(hits, hit_bitarray.count(), len(hit_bitarray), nan_div(hit_bitarray.count(),len(hit_bitarray)))
	avg_length_diff = nan_div(avg_length_diff, hits)
	avg_offset = nan_div(avg_offset, hits)
	hit_rate = nan_div(hits, float(n))
	mix_hit_rate = nan_div(mix_hits, float(n))
#	print(typematrix)
	return hits, hit_rate, mix_hit_rate, avg_length_diff, avg_offset, hit_bitarray, typematrix, variantsums, callsums

def aggregate_toolwise_statistics(stats_lists, tool_names):
	"""Given lists [(stats_list_ins_prec,stats_list_ins_recall,stats_list_del_prec,stats_list_del_recall),..] 
	that contain one entry for every tool (where each "stats_list" is a list of VariationStatistics).
	A list of ToolStatistics is returned."""
	assert len(tool_names) == len(stats_lists)
	result = []
	# store bitarrays to determine exclusive calls
	insertion_recall_bitarrays = []
	deletion_recall_bitarrays = []
	for name, (ins_prec_list, ins_recall_list, del_prec_list, del_recall_list) in zip(tool_names,stats_lists):
		tool_stats = ToolStatistics(name)
		hits, hit_rate, mix_hit_rate, avg_length_diff, avg_offset, hit_bitarray, typematrix, varsums, callsums = summarize_variation_stats_list(ins_prec_list)
		tool_stats.insertion_count = len(ins_prec_list)
		tool_stats.insertion_precision = hit_rate
		tool_stats.insertion_mix_hits = mix_hit_rate
#		print(hit_rate,file=sys.stderr)
		tool_stats.insertion_avg_lendiff = avg_length_diff
		tool_stats.insertion_avg_distance = avg_offset
		tool_stats.insertion_precision_types = typematrix
		tool_stats.insertion_precision_varsums = varsums
		tool_stats.insertion_precision_callsums = callsums
		hits, hit_rate, mix_hit_rate, avg_length_diff, avg_offset, hit_bitarray, typematrix, varsums, callsums = summarize_variation_stats_list(ins_recall_list)
		tool_stats.insertion_recall = hit_rate
#		print(hit_rate,file=sys.stderr)
		tool_stats.insertion_f = f_measure(tool_stats.insertion_precision, tool_stats.insertion_recall)
		tool_stats.insertion_recall_types = typematrix
		tool_stats.insertion_recall_varsums = varsums
		tool_stats.insertion_recall_callsums = callsums
		insertion_recall_bitarrays.append(hit_bitarray)
		hits, hit_rate, mix_hit_rate, avg_length_diff, avg_offset, hit_bitarray, typematrix, varsums, callsums = summarize_variation_stats_list(del_prec_list)
		tool_stats.deletion_count = len(del_prec_list)
		tool_stats.deletion_precision = hit_rate
		tool_stats.deletion_mix_hits = mix_hit_rate
		tool_stats.deletion_avg_lendiff = avg_length_diff
		tool_stats.deletion_avg_distance = avg_offset
		tool_stats.deletion_precision_types = typematrix
		tool_stats.deletion_precision_varsums = varsums
		tool_stats.deletion_precision_callsums = callsums
		hits, hit_rate, mix_hit_rate, avg_length_diff, avg_offset, hit_bitarray, typematrix, varsums, callsums = summarize_variation_stats_list(del_recall_list)
		tool_stats.deletion_recall = hit_rate
		tool_stats.deletion_f = f_measure(tool_stats.deletion_precision, tool_stats.deletion_recall)
		tool_stats.deletion_recall_types = typematrix
		tool_stats.deletion_recall_varsums = varsums
		tool_stats.deletion_recall_callsums = callsums
		deletion_recall_bitarrays.append(hit_bitarray)
		result.append(tool_stats)
	# compute exclusivity
	for tool_idx in range(len(result)):
		total_insertions = len(insertion_recall_bitarrays[tool_idx])
		total_deletions = len(deletion_recall_bitarrays[tool_idx])
		insertion_recall_others = bitarray(total_insertions)
		insertion_recall_others.setall(0)
		deletion_recall_others = bitarray(total_deletions)
		deletion_recall_others.setall(0)
		for i in range(len(result)):
			if i == tool_idx: continue
			assert len(insertion_recall_bitarrays[i]) == total_insertions
			insertion_recall_others |= insertion_recall_bitarrays[i]
			assert len(deletion_recall_bitarrays[i]) == total_deletions
			deletion_recall_others |= deletion_recall_bitarrays[i]
		exclusive_insertion_hits = (insertion_recall_bitarrays[tool_idx] & ~insertion_recall_others)
		exclusive_deletion_hits = (deletion_recall_bitarrays[tool_idx] & ~deletion_recall_others)
		result[tool_idx].insertion_exclusivity = nan_div(exclusive_insertion_hits.count(),float(total_insertions))
		result[tool_idx].deletion_exclusivity = nan_div(exclusive_deletion_hits.count(),float(total_deletions))
	return result

def typematrix_to_denovo_rate(typematrix):
	"""Returns fraction of correctly typed / inherited denovo calls."""
	idx_to_triotype = dict((i,triotype) for triotype, i in typedict.items())
	total = 0
	correct = 0
	inherited = 0
	for type1_idx, count in enumerate(typematrix[typedict['001']]):
		type1 = idx_to_triotype[type1_idx]
		total += count
		if type1 == '001':
			correct += count
		elif (type1[2] in ['1','2']) and ((type1[0] in ['1','2']) or (type1[1] in ['1','2'])):
			inherited += count
	return correct, inherited, total

def typematrix_to_3by3matrix(typematrix, individuals=set([0,1,2])):
	idx_to_triotype = dict((i,triotype) for triotype, i in typedict.items())
	result = [[0,0,0],[0,0,0],[0,0,0]]
	for type1_idx, l in enumerate(typematrix):
		type1 = idx_to_triotype[type1_idx]
		for type2_idx, count in enumerate(l):
			type2 = idx_to_triotype[type2_idx]
			for individual in individuals:
				i = int(type1[individual])
				j = int(type2[individual])
				result[i][j] += count
	return result

def typematrix_to_individual_rate(typematrix, compare_gt):
	"""Turns a trio type matrix into the rate of correct calls individual-wise."""
	if typematrix == None:
		return None
	idx_to_triotype = dict((i,triotype) for triotype, i in typedict.items())
	total = 0
	correct = 0
	for type1_idx, l in enumerate(typematrix):
		type1 = idx_to_triotype[type1_idx]
		for type2_idx, count in enumerate(l):
			type2 = idx_to_triotype[type2_idx]
			for i in range(3):
				total += count
				if compare_gt:
					if type1[i] == type2[i]: correct += count
				else:
					if (type1[i] == '0') == (type2[i] == '0'): correct += count
	return nan_div(correct, total)

def format_heading(s, width):
	assert len(s) + 4 <= width
	left = (width - 2 - len(s)) // 2
	right = width - 2 - len(s) - left
	return ('='*left) + ' ' + s + ' ' + ('='*right)

def format_range(s, width):
	assert len(s) + 6 <= width
	left = (width - 4 - len(s)) // 2
	right = width - 4 - len(s) - left
	return '|' + ('-'*left) + ' ' + s + ' ' + ('-'*right) + '|'

def left_pad(s, width):
	if len(s) >= width:
		return s
	else:
		return ' '*(width-len(s)) + s

def right_pad(s, width):
	if len(s) >= width:
		return s
	else:
		return s + ' '*(width-len(s))

def format_value(v, width, factor=100.0):
	s = '--' if math.isnan(v) else '%.1f'%(v*factor)
	return left_pad(s,width)

def format_value_tex(v, width, best, factor=100.0):
	if v == None:
		return left_pad('N/A',width)
	elif math.isnan(v):
		return left_pad('--',width)
	else:
		if v == best:
			return left_pad('\\textbf{%.1f}'%(v*factor), width)
		else:
			return left_pad('%.1f '%(v*factor), width)

def print_type_results_ascii(results, length_ranges, true_indel_counts):
	pass

def print_trio_typing_accuracy_ascii(results, length_ranges, true_indel_counts):
	idx_to_triotype = dict((i,triotype) for triotype, i in typedict.items())
	for length_range, true_indels, toolwise_results in zip(length_ranges,true_indel_counts,results):
		print('======================================================================')
		print('\nLength range %d-%d' % (length_range), '(insertions: %d, deletions %d)' % (true_indels))
		for tool_stats in toolwise_results:
			print('----------------------------------------------------------------------')
			print(tool_stats.name)
			total = 0
			wrong_count = 0
			# count_by_correctness[i] is the number of predictions for which i individuals have been correctly genotyped
			count_by_correctness = [0,0,0,0]
			errors = [[0,0,0],[0,0,0],[0,0,0]]
			total_errors = 0
			for calltype_idx, l in enumerate(tool_stats.deletion_precision_types):
				calltype = idx_to_triotype[calltype_idx]
				for truetype_idx, count in enumerate(l):
					truetype = idx_to_triotype[truetype_idx]
					total += count
					if truetype == '000':
						wrong_count += count
					else:
						correct = sum(calltype[i] == truetype[i] for i in range(3))
						count_by_correctness[correct] += count
						for i in range(3):
							if calltype[i] != truetype[i]:
								errors[int(calltype[i])][int(truetype[i])] += count
								total_errors += count
			print("Call wrong:                                         %6d %s"%(wrong_count, format_value(nan_div(wrong_count,total),5)))
			correct_calls = total - wrong_count
			for i in range(4):
				print("Call correct, genotyping correct for %d individuals: %6d %s %s"%(i, count_by_correctness[i], format_value(nan_div(count_by_correctness[i],total),5), format_value(nan_div(count_by_correctness[i],correct_calls),5)))
			print('---')
			for i in range(3):
				for j in range(3):
					if i == j: continue
					print('Error: prediction %d, but truth %d: %6d %s'%(i,j,errors[i][j], format_value(nan_div(errors[i][j],total_errors),5)))

def print_membership_results_ascii(results, length_ranges, true_indel_counts):
	
	classes = ['np','ch','fa','mo','c/f','c/m','m/f','c/m/f']

	def membershipmatrix_from_typematrix(typematrix):
#		print(typematrix)
		membershipmatrix = []
		for k in range(8):
			membershipmatrix.append([])
			for l in range(8):
				membershipmatrix[-1].append(0)
		for i in range(len(typematrix)):
			for j, entry in enumerate(typematrix[i]):
				membershipmatrix[type2member[i]][type2member[j]] += entry
#		print(membershipmatrix)
		return membershipmatrix

	for length_range, true_indels, toolwise_results in zip(length_ranges,true_indel_counts,results):

		print('\nLength range %d-%d' % (length_range), '(insertions: %d, deletions %d)' % (true_indels))

		for tool_stats in toolwise_results:
			
			del_prec_matrix = membershipmatrix_from_typematrix(tool_stats.deletion_precision_types)
			del_recall_matrix = membershipmatrix_from_typematrix(tool_stats.deletion_recall_types)

			precision = tool_stats.deletion_precision
			recall = tool_stats.deletion_recall
			
			# First: precision and classification of the tool's calls

			print("\n", tool_stats.name, ':\t', "Precision: ", precision, "\n\n========\n")
			outstring = "Class\tSum"
			print("\t\t\t\tColumns: true occurrence\n")
			for i in range(len(classes)):
				outstring += '\t%s' % (classes[i])
			outstring += '\n'
			rowtotal = []
			for i in range(len(del_prec_matrix)):
				rowtotal.append(sum(del_prec_matrix[i]))
			coltotal = []
			for j in range(len(del_prec_matrix[0])):
				coltotal.append(sum([s[j] for s in del_prec_matrix]))
			assert sum(rowtotal) == sum(coltotal)
			total = sum(rowtotal)
			for i in range(len(del_prec_matrix)):
				outstring += "%s\t%d\t" % (classes[i],rowtotal[i])
				for j in range(len(del_prec_matrix[i])):
					if rowtotal[i] > 0:
						outstring += "%.2f\t" % (100.0*(float(del_prec_matrix[i][j])/rowtotal[i]))
					else:
						outstring += "%.2f\t" % ((float(del_prec_matrix[i][j])))
				outstring += "\n"
			outstring += "All\t%d\t" % (total)
			for j in range(len(del_prec_matrix[0])):
				if total > 0:
					outstring += "%.2f\t" % (100.0*(float(coltotal[j])/total))
				else:
					outstring += "%.2f\t" % ((float(coltotal[j])))

			print(outstring)
			print("\n================================\n")
			# Second: recall and classification of true annotations

			print("\n", tool_stats.name, ':\t', "Recall: ", recall, "\n\n========\n")
			print("\t\t\t\tColumns are call classes\n")
			outstring = "True\tSum"
			for i in range(len(classes)):
				outstring += '\t%s' % (classes[i])
			outstring += '\n'			
			rowtotal = []
			for i in range(len(del_recall_matrix)):
				rowtotal.append(sum(del_recall_matrix[i]))
			coltotal = []
			for j in range(len(del_recall_matrix[0])):
				coltotal.append(sum([s[j] for s in del_recall_matrix]))
			assert sum(rowtotal) == sum(coltotal)
			total = sum(rowtotal)
			for i in range(len(del_recall_matrix)):
				outstring += "%s\t%d\t" % (classes[i],rowtotal[i])
				for j in range(len(del_recall_matrix[i])):
					if rowtotal[i] > 0:
						outstring += "%.2f\t" % (100.0*(float(del_recall_matrix[i][j])/rowtotal[i]))
					else:
						outstring += "%.2f\t" % ((float(del_recall_matrix[i][j])))
				outstring += "\n"
			outstring += "All\t%d\t" % (total)
			for j in range(len(del_recall_matrix[0])):
				if total > 0:
					outstring += "%.2f\t" % (100.0*(float(coltotal[j])/total))
				else:
					outstring += "%.2f\t" % ((float(coltotal[j])))

			print(outstring)
			print("\n================================\n")
					
#			tool_stats.deletion_precision_varsums
#			tool_stats.deletion_precision_callsums

	
def print_trio_results_ascii(results, length_ranges, true_indel_counts):

	trioclasses = ['000', '001', '010/100', '011/101', '021/201', '110' , '111', '112' ,'121/211', '122/212', '222', '002', '012/102', '020/200', '022/202', '120/210', '220', '221']

	def triomatrix_from_typematrix(typematrix):

		triomatrix = []
		for k in range(18):
			triomatrix.append([])
			for l in range(18):
				triomatrix[-1].append(0)
		for i in range(len(typematrix)):
			for j, entry in enumerate(typematrix[i]):
				#print(type2trio[i], type2trio[j], file=sys.stderr)
				triomatrix[type2trio[i]][type2trio[j]] += entry
		return triomatrix

	for length_range, true_indels, toolwise_results in zip(length_ranges,true_indel_counts,results):

		print('\nLength range %d-%d' % (length_range), '(insertions: %d, deletions %d)' % (true_indels))

		for tool_stats in toolwise_results:
			
			del_prec_matrix = triomatrix_from_typematrix(tool_stats.deletion_precision_types)
			del_recall_matrix = triomatrix_from_typematrix(tool_stats.deletion_recall_types)

			precision = tool_stats.deletion_precision
			recall = tool_stats.deletion_recall
			
			# First: precision and classification of the tool's calls

			print("\n", tool_stats.name, ':\t', "Precision: ", precision, "\n\n========\n")
			outstring = "Class\tSum"
			print("\t\t\t\tColumns: true occurrence\n")
			for i in range(len(trioclasses)):
				outstring += '\t%s' % (trioclasses[i])
			outstring += '\n'
			rowtotal = []
			for i in range(len(del_prec_matrix)):
				rowtotal.append(sum(del_prec_matrix[i]))
			coltotal = []
			for j in range(len(del_prec_matrix[0])):
				coltotal.append(sum([s[j] for s in del_prec_matrix]))
			assert sum(rowtotal) == sum(coltotal)
			total = sum(rowtotal)
			for i in range(len(del_prec_matrix)):
				outstring += "%s\t%d\t" % (trioclasses[i],rowtotal[i])
				for j in range(len(del_prec_matrix[i])):
					if rowtotal[i] > 0:
						outstring += "%.2f\t" % (100.0*(float(del_prec_matrix[i][j])/rowtotal[i]))
					else:
						outstring += "%.2f\t" % ((float(del_prec_matrix[i][j])))
				outstring += "\n"
			outstring += "All\t%d\t" % (total)
			for j in range(len(del_prec_matrix[0])):
				if total > 0:
					outstring += "%.2f\t" % (100.0*(float(coltotal[j])/total))
				else:
					outstring += "%.2f\t" % ((float(coltotal[j])))

			print(outstring)
			print("\n================================\n")
			# Second: recall and classification of true annotations

			print("\n", tool_stats.name, ':\t', "Recall: ", recall, "\n\n========\n")
			print("\t\t\t\tColumns are call classes\n")
			outstring = "True\tSum"
			for i in range(len(trioclasses)):
				outstring += '\t%s' % (trioclasses[i])
			outstring += '\n'			
			rowtotal = []
			for i in range(len(del_recall_matrix)):
				rowtotal.append(sum(del_recall_matrix[i]))
			coltotal = []
			for j in range(len(del_recall_matrix[0])):
				coltotal.append(sum([s[j] for s in del_recall_matrix]))
			assert sum(rowtotal) == sum(coltotal)
			total = sum(rowtotal)
			for i in range(len(del_recall_matrix)):
				outstring += "%s\t%d\t" % (trioclasses[i],rowtotal[i])
				for j in range(len(del_recall_matrix[i])):
					if rowtotal[i] > 0:
						outstring += "%.2f\t" % (100.0*(float(del_recall_matrix[i][j])/rowtotal[i]))
					else:
						outstring += "%.2f\t" % ((float(del_recall_matrix[i][j])))
				outstring += "\n"
			outstring += "All\t%d\t" % (total)
			for j in range(len(del_recall_matrix[0])):
				if total > 0:
					outstring += "%.2f\t" % (100.0*(float(coltotal[j])/total))
				else:
					outstring += "%.2f\t" % ((float(coltotal[j])))

			print(outstring)
			print("\n================================\n")

def print_genotype_correctness_table_ascii(results, length_ranges, true_indel_counts):
	"""Input: list with a lists of ToolStatistics for each length range."""
	assert len(results) == len(length_ranges)
	# width of first column
	w0 = max(max(len(t.name) for t in results[0]) + 1, 4) + 8
	# width of other columns
	w = 8
	# total width
	wt = w0 + 10*w
	print('='*wt)
	print(right_pad('Tools',w0), left_pad('Total',w), ''.join(left_pad('%d->%d'%(i,j),w) for i in range(3) for j in range(3)), sep='')
	for length_range,true_indels,toolwise_results in zip(length_ranges,true_indel_counts,results):
		print('-'*wt)
		print('Length range %d-%d'%length_range,'(insertions: %d, deletions %d)'%true_indels)
		for tool_stats in toolwise_results:
			overall_table = typematrix_to_3by3matrix(tool_stats.deletion_precision_types, set([0,1,2]))
			parents_table = typematrix_to_3by3matrix(tool_stats.deletion_precision_types, set([0,1]))
			child_table = typematrix_to_3by3matrix(tool_stats.deletion_precision_types, set([2]))
			for suffix, table in [('-overall',overall_table),('-parents',parents_table),('-child',child_table)]:
				total = sum(sum(x) for x in table)
				totals = [sum(x) for x in table]
				print(right_pad(tool_stats.name+suffix,w0), left_pad(str(total),w), ''.join(format_value(nan_div(table[i][j],totals[i]),w) for i in range(3) for j in range(3)), sep='')
	print('='*wt)
	print()

def print_denovo_table_ascii(results, length_ranges, true_indel_counts):
	"""Input: list with a lists of ToolStatistics for each length range."""
	assert len(results) == len(length_ranges)
	# width of first column
	w0 = max(max(len(t.name) for t in results[0]) + 1, 4)
	# width of other columns
	w = 15
	# total width
	wt = w0 + 4*w
	print('='*wt)
	print(right_pad('Tools',w0), left_pad('Total',w), left_pad('Recall',w), left_pad('Precision',w), left_pad('Inherited',w), sep='')
	for length_range,true_indels,toolwise_results in zip(length_ranges,true_indel_counts,results):
		print('-'*wt)
		print('Length range %d-%d'%length_range,'(insertions: %d, deletions %d)'%true_indels)
		for tool_stats in toolwise_results:
			recall_correct, recall_inherited, recall_total = typematrix_to_denovo_rate(tool_stats.deletion_recall_types)
			precision_correct, precision_inherited, precision_total = typematrix_to_denovo_rate(tool_stats.deletion_precision_types)
			recall_rate = nan_div(recall_correct,recall_total)
			precision_rate =  nan_div(precision_correct,precision_total)
			inherited_rate =  nan_div(precision_inherited,precision_total)
			print(right_pad(tool_stats.name,w0), left_pad(str(precision_total),w), format_value(recall_rate,w), format_value(precision_rate,w), format_value(inherited_rate,w), sep='')
	print('='*wt)
	print()
	
def print_results_ascii(results, length_ranges, true_indel_counts, print_typing):
	"""Input: list with a lists of ToolStatistics for each length range."""
	assert len(results) == len(length_ranges)
	# width of first column
	w0 = max(max(len(t.name) for t in results[0]) + 1, 4)
	# width of other columns
	w = 10
	# ============ print insertions ==============
	wt = w0 + 8*w
	print(format_heading("INSERTIONS", wt))
	print(right_pad('Tool',w0), left_pad('Abs.',w), left_pad('Prec.',w), left_pad('Mix.',w), left_pad('Recall',w), left_pad('Excl.',w), left_pad('F',w), left_pad('Len.Diff.',w), left_pad('Dist.',w), sep='')
	for length_range,true_indels,toolwise_results in zip(length_ranges,true_indel_counts,results):
		print('-'*wt)
		print('Length range %d-%d'%length_range,'(true insertions: %d)'%true_indels[0])
		for tool_stats in toolwise_results:
			print(right_pad(tool_stats.name,w0), left_pad(str(tool_stats.insertion_count),w), format_value(tool_stats.insertion_precision,w), format_value(tool_stats.insertion_mix_hits,w), format_value(tool_stats.insertion_recall,w), format_value(tool_stats.insertion_exclusivity,w), format_value(tool_stats.insertion_f,w), format_value(tool_stats.insertion_avg_lendiff,w,1.0), format_value(tool_stats.insertion_avg_distance,w,1.0), sep='')
	print('='*wt + '\n')
	# ============ print deletions ==============
	# total width
	if print_typing:
		wt = w0 + 10*w
	else:
		wt = w0 + 8*w
	print(format_heading("DELETIONS", wt))
	if print_typing:
		print(right_pad('Tool',w0), left_pad('Abs.',w), left_pad('Prec.',w), left_pad('Mix.',w), left_pad('Ind.Prec.',w), left_pad('GT.Prec.',w), left_pad('Recall',w), left_pad('Excl.',w), left_pad('F',w), left_pad('Len.Diff.',w), left_pad('Dist.',w), sep='')
	else:
		print(right_pad('Tool',w0), left_pad('Abs.',w), left_pad('Prec.',w), left_pad('Mix.',w), left_pad('Recall',w), left_pad('Excl.',w), left_pad('F',w), left_pad('Len.Diff.',w), left_pad('Dist.',w), sep='')
	for length_range,true_indels,toolwise_results in zip(length_ranges,true_indel_counts,results):
		print('-'*wt)
		print('Length range %d-%d'%length_range,'(true deletions %d)'%true_indels[1])
		for tool_stats in toolwise_results:
			if print_typing:
				deletion_ind_prec = typematrix_to_individual_rate(tool_stats.deletion_precision_types, False)
				deletion_gt_prec = typematrix_to_individual_rate(tool_stats.deletion_precision_types, True)
				print(right_pad(tool_stats.name,w0), left_pad(str(tool_stats.deletion_count),w), format_value(tool_stats.deletion_precision,w), format_value(tool_stats.deletion_mix_hits,w), format_value(deletion_ind_prec,w), format_value(deletion_gt_prec,w), format_value(tool_stats.deletion_recall,w), format_value(tool_stats.deletion_exclusivity,w), format_value(tool_stats.deletion_f,w), format_value(tool_stats.deletion_avg_lendiff,w,1.0), format_value(tool_stats.deletion_avg_distance,w,1.0), sep='')
			else:
				print(right_pad(tool_stats.name,w0), left_pad(str(tool_stats.deletion_count),w), format_value(tool_stats.deletion_precision,w), format_value(tool_stats.deletion_mix_hits,w), format_value(tool_stats.deletion_recall,w), format_value(tool_stats.deletion_exclusivity,w), format_value(tool_stats.deletion_f,w), format_value(tool_stats.deletion_avg_lendiff,w,1.0), format_value(tool_stats.deletion_avg_distance,w,1.0), sep='')
	print('='*wt)

def print_results_latex(results, length_ranges, true_indel_counts):
	"""Input: list with a lists of ToolStatistics for each length range."""
	assert len(results) == len(length_ranges)
	# width of first column
	w0 = max(max(len(t.name.replace('.vcf','').replace('mean', 'm').replace('stddev', 'sd').replace('_','-')) for t in results[0]) + 1, 4)
	# width of other columns
	w = 14
	print('\\section{Overall performance}')
	print('\\subsection{Insertions}')
	print('\\begin{longtable}{lrrrrrrrr}')
	print('\\hline')
	print(' '*w0, left_pad('Abs.',w), left_pad('Prec.',w), left_pad('Mix.',w), left_pad('Rec.',w), left_pad('Exc.',w), left_pad('F.',w), left_pad('$\Delta$Len.',w), left_pad('Dist.',w), sep=' & ', end='\\\\\n')
	print('\hline')
	for length_range,true_indels,toolwise_results in zip(length_ranges,true_indel_counts,results):
		print('\\multicolumn{8}{l}{\\textbf{Length Range %d--%d}'%length_range, '(%s true insertions)}\\\\'%format(true_indels[0],',d'))
		best = ToolStatistics()
		for tool_stats in toolwise_results:
			best.improve(tool_stats)
		for tool_stats in toolwise_results:
			print(
				right_pad(tool_stats.name.replace('.vcf','').replace('mean', 'm').replace('stddev', 'sd').replace('_','-'),w0),
				right_pad(str(tool_stats.insertion_count), w),
				format_value_tex(tool_stats.insertion_precision,w,best.insertion_precision),
				format_value_tex(tool_stats.insertion_mix_hits,w,best.insertion_mix_hits),
				format_value_tex(tool_stats.insertion_recall,w,best.insertion_recall),
				format_value_tex(tool_stats.insertion_exclusivity,w,best.insertion_exclusivity),
				format_value_tex(tool_stats.insertion_f,w,best.insertion_f),
				format_value_tex(tool_stats.insertion_avg_lendiff,w,best.insertion_avg_lendiff,1.0),
				format_value_tex(tool_stats.insertion_avg_distance,w,best.insertion_avg_distance,1.0),
			sep=' & ', end='\\\\\n')
		print('\hline')
	print('\\end{longtable}')
	print('\\subsection{Deletions}')
	print('\\begin{longtable}{lrrrrrrrr}')
	print('\\hline')
	print(' '*w0, left_pad('Abs.',w), left_pad('Prec.',w), left_pad('Mix.',w), left_pad('Rec.',w), left_pad('Exc.',w), left_pad('F.',w), left_pad('$\Delta$Len.',w), left_pad('Dist.',w), sep=' & ', end='\\\\\n')
	print('\hline')
	for length_range,true_indels,toolwise_results in zip(length_ranges,true_indel_counts,results):
		print('\\multicolumn{8}{l}{\\textbf{Length Range %d--%d}'%length_range, '(%s true deletions)}\\\\'%format(true_indels[1],',d'))
		best = ToolStatistics()
		for tool_stats in toolwise_results:
			best.improve(tool_stats)
		for tool_stats in toolwise_results:
			print(
				right_pad(tool_stats.name.replace('.vcf', '').replace('_', '-'),w0),
				right_pad(str(tool_stats.deletion_count), w),
				format_value_tex(tool_stats.deletion_precision,w,best.deletion_precision),
				format_value_tex(tool_stats.deletion_mix_hits,w,best.deletion_mix_hits),
				format_value_tex(tool_stats.deletion_recall,w,best.deletion_recall),
				format_value_tex(tool_stats.deletion_exclusivity,w,best.deletion_exclusivity),
				format_value_tex(tool_stats.deletion_f,w,best.deletion_f),
				format_value_tex(tool_stats.deletion_avg_lendiff,w,best.deletion_avg_lendiff,1.0),
				format_value_tex(tool_stats.deletion_avg_distance,w,best.deletion_avg_distance,1.0),
			sep=' & ', end='\\\\\n')
		print('\hline')
	print('\\end{longtable}')
	print('\\subsection{Table Legend}')
	print('\\begin{itemize}')
	print('\\item \\textbf{Abs.:} \\emph{Absolute number} of predictions made in this length range')
	print('\\item \\textbf{Prec.:} \\emph{Precision}, the percentage of predictions in that length range that match a true deletion/insertion.')
	print('\\item \\textbf{Mix.:} Percentage of predictions that don\'t match a true insertion/deletion but a \\emph{mixed insertion/deletion event} of the same/similar effective length.')
	print('\\item \\textbf{Rec.:} \\emph{Recall}, the percentage of true insertions/deletions in that length range that have been discovered.')
	print('\\item \\textbf{Exc.:} \\emph{Exclusive calls}: percentage of true insertions/deletions that are \\emph{only} discovered by this tool.')
	print('\\item \\textbf{F:} \\emph{$F$-Measure}: $2\cdot\mbox{precision}\cdot\mbox{recall}/(\mbox{precision}+\mbox{recall})$. This integrates precision and recall into one statistic.')
	print('\\item \\textbf{$\Delta$Len.:} \\emph{Length difference}: average length difference between prediction and true insertion/deletion (averaged over all predictions that match a true annotation)')
	print('\\item \\textbf{Dist.:} \\emph{Distance}: average center distance between prediction and true insertion/deletion (averaged over all predictions that match a true annotation)')
	print('\\end{itemize}')

def tag_to_str(tag):
	if tag == None: return 'No Tag'
	else: return str(tag)

def print_tag_table(stats_list, variants0, variants1, all_tags0, all_tags1, title, caption_total, caption_wrong, latex_output):
	class TagStatistics:
		def __init__(self):
			self.total = 0
			self.wrong = 0
			self.target_tags = defaultdict(int)
	t = defaultdict(TagStatistics)
	for v in stats_list:
		coord1, coord2, coord3, var_type, from_tags = variants0.get(v.chromosome, v.index)
		for from_tag in from_tags:
			t[from_tag].total += 1
			if len(v.hits) == 0:
				t[from_tag].wrong += 1
			else:
				all_to_tags = set()
				try:
					for index,length_diff,offset in v.hits:
						coord1, coord2, coord3, var_type, to_tags = variants1.get(v.chromosome, index)
						all_to_tags.update(to_tags)
				except:
					pass
				for to_tag in all_to_tags:
					t[from_tag].target_tags[to_tag] += 1
	w0 = max(len(tag_to_str(x)) for x in all_tags0) + 1
	w = max(10, max(len(tag_to_str(x)) for x in all_tags1) + 1, len(caption_total), len(caption_wrong))
	if latex_output:
		print('\\subsection*{%s}'%title)
		print('\\begin{longtable}[l]{lrr%s}'%('r'*len(all_tags1)))
		print('\\hline')
		print(' '*w0, left_pad(caption_total,w), sep=' & ', end=' & ')
		print(left_pad(caption_wrong,w), end='')
		for to_tag in all_tags1:
			print(' & ',left_pad(tag_to_str(to_tag),w), sep='', end='')
		print('\\\\')
		print('\hline')
	else:
		left_fill = '='*10
		right_fill = '='*(100 - len(title) - len(left_fill))
		print('\n\n%s %s %s'%(left_fill,title,right_fill))
		print(' '*w0, left_pad(caption_total,w), sep='', end='')
		print(left_pad(caption_wrong,w), end='')
		for to_tag in all_tags1:
			print(left_pad(tag_to_str(to_tag),w), end='')
		print()
	for from_tag in all_tags0:
		total = t[from_tag].total
		print(right_pad(tag_to_str(from_tag),w0), end=' & ' if latex_output else '')
		print(left_pad(str(total),w), end=' & ' if latex_output else '')
		n = t[from_tag].wrong
		print(left_pad('%d/%.1f'%(n, nan_div(100.0*n,total)),w), end='')
		for to_tag in all_tags1:
			n = t[from_tag].target_tags[to_tag]
			print(' & ' if latex_output else '', left_pad('%d/%.1f'%(n, nan_div(100.0*n,total)),w), sep='', end='')
		print('\\\\' if latex_output else '')
	if latex_output:
		print('\hline')	
		print('\\end{longtable}')

def extract_accuracy_stats(var_stats):
	"""Reads a list of VariationStatistics and returns a list [(length_diff,offset)...]."""
	result = []
	for v in var_stats:
		if v.is_hit():
			index, length_diff, offset, typing = v.get_best_hit()
			result.append((length_diff, offset))
	return result

def tag_string(tags):
	if tags == None or len(tags) == 0:
		return "None"
	return ';'.join(str(x) for x in tags)

def main():

	parser = OptionParser(usage=usage)

	hit_count_options = OptionGroup(parser, "Options controlling how hits are counted")
	hit_count_options.add_option("-M", action="store", dest="mode", default="fixed_distance",
				     help='Operation mode: "fixed_distance" or "overlap" or "significant" (default: "fixed_distance").')
	hit_count_options.add_option("-c", action="store", dest="chromosomes", default=None,
				     help="Comma separated list of chromosomes to consider (default: all).")
	hit_count_options.add_option("-R", action="store", dest="length_ranges", default="9-18,19-48,49-98,99-248,249-998,999-50000",
				     help="Comma-separated list of length ranges to be evaluated separately (default: \"10-19,20-49,50-99,100-249,250-999,1000-50000\").")
	hit_count_options.add_option("-o", action="store", dest="offset", type=int, default=50,
				     help="Allowed distance of centers of prediction and annotation in mode \"fixed_distance\"; has no effect in other modes (default: 50).")
	hit_count_options.add_option("-z", action="store", dest="difflength", type=int, default=20,
				     help="Difference in length allowed to establish hit, e.g. -z 20 allows predicted deletion to match an annotated deletion of length +- 20 (default: 20)")
	hit_count_options.add_option("-C", action="store", dest="chromosome_lengths_file", default=None,
				     help='File with chromosome lengths, needed when running in mode "significant".')
	hit_count_options.add_option("-p", action="store", dest="siglevel", type=float, default=0.01,
				     help="Significance level (i.e. p-value threshold) for mode \"significant\"; has no effect in other modes (default: 0.01)")
	hit_count_options.add_option("-f", action="store_true", dest="trio", default=False,
					help="If set, expects trio call file.")
#	hit_count_options.add_option("-j", action="store_true", dest="merge", default=False, help="First merges predictions for the given set of predictions, usually from different tools.")
#	hit_count_options.add_option("-m", action="store", dest="mergeoffset", type=int, default=50,
#				     help="maximum distance allowed between centerpoints for merging calls")
#	hit_count_options.add_option("-y", action="store", dest="mergedifflength", type=int, default=20,
#				     help="maximum difference in length allowed between centerpoints for merging calls")
	
	output_options = OptionGroup(parser, "Options controlling output")
	output_options.add_option("-N", action="store", dest="tool_names", default=None,
					help="Comma-separated list of names of tools to be used in output (default: use filenames).")
	output_options.add_option("-L", action="store_true", dest="latex_output", default=False,
					help="LaTeX output.")
	output_options.add_option("-T", action="store_true", dest="print_tag_stats", default=False,
					help="Create statistics on tags (field 5 in input files), i.e. print tables showing which tags in predictions match which tags in true variants.")
	output_options.add_option("-P", action="store", dest="plot_directory", default=None,
					help="Plot accuracy of predictions for each tool and length range and save plots to given directory.")
	output_options.add_option("-l", action="store", dest="true_var_outfile", default=None,
					help="Write list of (considered) true variants and information on which tools predicted them correctly to the given filename.")
	output_options.add_option("-t", action="store", dest="toolwise_outfile", default=None,
				  help="For each tool, write a list of made predictions and whether each predictions was true to the given filename. The filename must contain \"{tool}\", which is replaced by each tools name.")
	output_options.add_option("-m", action="store", dest="triomode", default=None,
				  help='Determines what statistics on trios are output. "membership" is untyped family membership, "summary" gives summary of correctly typed calls, "ancestry" is typed, but does not distinguish between mother and father, "full" is the full typing possible')
					     

	parser.add_option_group(hit_count_options)
	parser.add_option_group(output_options)

	(options, args) = parser.parse_args()
	if (len(args) < 2):
		parser.print_help()
		sys.exit(1)
	if options.plot_directory != None:
		if not os.path.isdir(options.plot_directory):
			print('Error: directory "%s" does not exist (option -P)'%options.plot_directory, file=sys.stderr)
			return 1
		import matplotlib
		matplotlib.use('pdf')
	print('Reading file', args[0], file=sys.stderr)
	true_variants = VariationList(args[0], options.trio)
	predictions_lists = []
	filenames = args[1:]

	for filename in filenames:
		print('Reading file', filename, file=sys.stderr)
		predictions_lists.append(VariationList(filename, options.trio))
	if options.chromosomes != None:
		chromosomes = set(options.chromosomes.split(','))
	else:
		chromosomes = set()
		chromosomes.update(true_variants.get_chromosomes())
		for predictions in predictions_lists:
			chromosomes.update(predictions.get_chromosomes())
	if options.tool_names == None:
		tool_names = args[1:]
		for n,name in enumerate(tool_names):
		  	tool_names[n] = os.path.basename(name)
	else:
		tool_names = options.tool_names.strip().split(',')
		if len(tool_names) != len(predictions_lists):
			print('Error: %d tools names given (option -N), but %d predictions present.'%(len(tool_names),len(predictions)))
			return 1
	if not options.mode in ['overlap','fixed_distance','significant']:
		print('Error: Invalid argument to option -D', file=sys.stderr)
		return 1
	if options.mode == 'significant':
		# TODO: Right now, mode "significant" depends on options.offset, which it should not
		print('Error: mode "significant" not fully implemented.', file=sys.stderr)
		return 1
		if options.chromosome_lengths_file == None:
			print('Error: Option -C is required when running in "significant" mode (chosen by option -D).', file=sys.stderr)
			return 1
		chromosome_lengths = dict([(f[0].lower(),int(f[2])) for f in (s.split() for s in open(options.chromosome_lengths_file))])
		true_deletion_stats = compute_count_stats(true_variants, chromosome_lengths, 0, 'DEL')
		true_insertion_stats = compute_count_stats(true_variants, chromosome_lengths, 0, 'INS')
	else:
		chromosome_lengths = None
		true_deletion_stats = None
		true_insertion_stats = None
	if options.mode != 'fixed_distance':
		options.offset = None
	try:
		length_ranges = [(int(a),int(b)) for a,b in (s.split('-') for s in options.length_ranges.strip().split(','))]
	except:
		print('Error parsing length ranges "%s" (option -R).'%options.length_ranges, file=sys.stderr)
		return 1
	# result list containing a list of ToolStatistics for each length range
	results = []
	# number of true insertions/deletions per length range
	true_indel_counts = []
	all_stats_lists = []
	for min_length, max_length in length_ranges:
		print('Computing statistics for length range %d-%d'%(min_length, max_length), file=sys.stderr)
		stats_lists = []
		for i,predictions in enumerate(predictions_lists):
			del_recall_list = true_variants.deletion_hit_statistics(predictions, chromosomes, true_deletion_stats, options.mode, options.trio, min_length, max_length, options.offset, options.difflength, options.siglevel, None)
			del_prec_list = predictions.deletion_hit_statistics(true_variants, chromosomes, true_deletion_stats, options.mode, options.trio, min_length, max_length, options.offset, options.difflength, options.siglevel, None)
			ins_recall_list = true_variants.insertion_hit_statistics(predictions, chromosomes, true_insertion_stats, options.mode, options.trio, min_length, max_length, options.offset, options.difflength, options.siglevel, None)
			ins_prec_list = predictions.insertion_hit_statistics(true_variants, chromosomes, true_insertion_stats, options.mode, options.trio, min_length, max_length, options.offset, options.difflength, options.siglevel, None)
			stats_lists.append((ins_prec_list, ins_recall_list, del_prec_list, del_recall_list))
			if i == 0:
				true_indel_counts.append((len(ins_recall_list),len(del_recall_list)))
		all_stats_lists.append(stats_lists)
		results.append(aggregate_toolwise_statistics(stats_lists, tool_names))
	if options.latex_output:
		print('\\documentclass[10pt]{article}')
		print('\\usepackage[margin=1.0in]{geometry}')
		print('\\usepackage{longtable}')
		print('\\usepackage{graphicx}')
		print('\\usepackage{listings}')
		print('\\lstset{breaklines=true,breakatwhitespace=false,basicstyle=\\ttfamily}')
		print('\\begin{document}')
		print('\\scriptsize')
		print('\\section{Command line}')
		print('\\begin{lstlisting}')
		print(' '.join(sys.argv))
		print('\\end{lstlisting}')
		print_results_latex(results, length_ranges, true_indel_counts)
	else:
		print('command line:',' '.join(sys.argv))
		if options.triomode == "membership":
			print_membership_results_ascii(results, length_ranges, true_indel_counts)
		elif options.triomode == "full":
			print_trio_results_ascii(results, length_ranges, true_indel_counts)
		elif options.triomode == "summary":
			print_trio_typing_accuracy_ascii(results, length_ranges, true_indel_counts)
		if options.trio:
			print_genotype_correctness_table_ascii(results, length_ranges, true_indel_counts)
			print_denovo_table_ascii(results, length_ranges, true_indel_counts)
		print_results_ascii(results, length_ranges, true_indel_counts, options.trio)
	if options.print_tag_stats:
		if options.latex_output:
			print('\\pagebreak')
			print('\\section{Tag-wise statistics}')
		truth_tags = list(true_variants.get_all_tags())
		truth_tags.sort()
		for tool_idx, (tool_name, predictions) in enumerate(zip(tool_names, predictions_lists)):
			predictions_tags = list(predictions.get_all_tags())
			predictions_tags.sort()
			for range_idx, (min_length, max_length) in enumerate(length_ranges):
				ins_prec_list, ins_recall_list, del_prec_list, del_recall_list = all_stats_lists[range_idx][tool_idx]
				print_tag_table(ins_prec_list, predictions, true_variants, predictions_tags, truth_tags, '%s: insertion predictions (precision) %d-%d'%(tool_name,min_length,max_length), 'Predictions', 'FP', options.latex_output)
				print_tag_table(ins_recall_list, true_variants, predictions, truth_tags, predictions_tags, '%s: insertion annotations (recall) %d-%d'%(tool_name,min_length,max_length), 'Annotations', 'FN', options.latex_output)
				print_tag_table(del_prec_list, predictions, true_variants, predictions_tags, truth_tags, '%s: deletion predictions (precision) %d-%d'%(tool_name,min_length,max_length), 'Predictions', 'FP', options.latex_output)
				print_tag_table(del_recall_list, true_variants, predictions, truth_tags, predictions_tags, '%s: deletion annotations (recall) %d-%d'%(tool_name,min_length,max_length), 'Annotations', 'FN', options.latex_output)
	# create accuracy plots?
	if options.plot_directory != None:
		if options.latex_output: 
			print('\\pagebreak')
			print('\\section{Prediction accuracy}')
		for tool_idx, (tool_name, predictions) in enumerate(zip(tool_names, predictions_lists)):
			if options.latex_output: print('\\subsection{%s}'%tool_name)
			predictions_tags = list(predictions.get_all_tags())
			predictions_tags.sort()
			for range_idx, (min_length, max_length) in enumerate(length_ranges):
				ins_prec_list, ins_recall_list, del_prec_list, del_recall_list = all_stats_lists[range_idx][tool_idx]
				del_accuracy_stats = extract_accuracy_stats(del_prec_list)
				del_filename = '%s/%s_deletions_%d-%d.pdf'%(options.plot_directory, tool_name, min_length, max_length)
				print('Creating plot', del_filename, file=sys.stderr)
				scatter_hist(del_accuracy_stats, del_filename, "%s: correct deletion predictions of length %d-%d (total: %d)"%(tool_name,min_length,max_length,len(del_accuracy_stats)), "Length difference", "Distance")
				ins_accuracy_stats = extract_accuracy_stats(ins_prec_list)
				ins_filename = '%s/%s_insertions_%d-%d.pdf'%(options.plot_directory, tool_name, min_length, max_length)
				print('Creating plot', ins_filename, file=sys.stderr)
				scatter_hist(ins_accuracy_stats, ins_filename, "%s: correct insertion predictions of length %d-%d (total: %d)"%(tool_name,min_length,max_length,len(ins_accuracy_stats)), "Length difference", "Distance")
				if options.latex_output:
					print('\\begin{center}')
					print('\\includegraphics[width=\\textwidth]{%s}'%del_filename)
					print('\\end{center}')
					print('\\begin{center}')
					print('\\includegraphics[width=\\textwidth]{%s}'%ins_filename)
					print('\\end{center}')
	if options.true_var_outfile != None:
		f = open(options.true_var_outfile, 'w')
		print('#true_chrom true_coord1 true_coord2 true_var_type true_tag', end='', file=f)
		for tool_name in tool_names:
			print(' {0}_coord1 {0}_coord2 {0}_tag'.format(tool_name), end='', file=f)
		print(file=f)
		for range_idx, (min_length, max_length) in enumerate(length_ranges):
			def print_list(l):
				for i in range(len(l[0])):
					v = l[0][i]
					coord1, coord2, coord3, var_type, tags = true_variants.get(v.chromosome, v.index)
					print(v.chromosome, coord1+1, coord2, var_type, tag_string(tags), end='', file=f)
					for tool_idx in range(len(tool_names)):
						if l[tool_idx][i].is_hit():
							index, length_diff, offset, typing = l[tool_idx][i].get_best_hit()
							pred_coord1, pred_coord2, pred_coord3, pred_var_type, pred_tags = predictions_lists[tool_idx].get(v.chromosome, index)
							print(' ',pred_coord1+1, ' ', pred_coord2, ' ', tag_string(pred_tags), sep='', end='', file=f)
						else:
							print(' -- -- --', end='', file=f)
					print(file=f)
			del_recall_lists = [del_recall_list for ins_prec_list, ins_recall_list, del_prec_list, del_recall_list in all_stats_lists[range_idx]]
			print_list(del_recall_lists)
			ins_recall_lists = [ins_recall_list for ins_prec_list, ins_recall_list, del_prec_list, del_recall_list in all_stats_lists[range_idx]]
			print_list(ins_recall_lists)
		f.close()
	if options.toolwise_outfile != None:
		if options.toolwise_outfile.find('{tool}') == -1:
			print("Error: filename given with option -t must contain \"{tool}\".", file=sys.stderr)
			return 1
		for tool_idx, tool_name in enumerate(tool_names):
			filename = options.toolwise_outfile.replace('{tool}', tool_name)
			f = open(filename, 'w')
			print('#{0}_chrom {0}_coord1 {0}_coord2 {0}_var_type {0}_tag matches_mixed_event true_coord1 true_coord2 true_tag'.format(tool_name), file=f)
			for range_idx, (min_length, max_length) in enumerate(length_ranges):
				def print_list(l):
					for v in l:
						coord1, coord2, coord3, var_type, tags = predictions_lists[tool_idx].get(v.chromosome, v.index)
						print(v.chromosome, coord1+1, coord2, var_type, tag_string(tags), v.is_mix_hit(), end='', file=f)
						if v.is_hit():
							index, length_diff, offset, typing = v.get_best_hit()
							true_coord1, true_coord2, true_coord3, true_var_type, true_tags = true_variants.get(v.chromosome, index)
							print(' ',true_coord1+1, ' ', true_coord2, ' ', tag_string(true_tags), sep='', file=f)
						else:
							print(' -- -- --', file=f)
				ins_prec_list, ins_recall_list, del_prec_list, del_recall_list = all_stats_lists[range_idx][tool_idx]
				print_list(del_prec_list)
				print_list(ins_prec_list)
			f.close()
	if options.latex_output:
		print('\\end{document}')

if __name__ == '__main__':
	sys.exit(main())