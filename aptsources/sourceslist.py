#  sourceslist.py - Provide an abstraction of the sources.list
#
#  Copyright (c) 2004-2009 Canonical Ltd.
#  Copyright (c) 2004 Michiel Sikkes
#  Copyright (c) 2006-2007 Sebastian Heinlein
#
#  Authors: Michiel Sikkes <michiel@eyesopened.nl>
#           Michael Vogt <mvo@debian.org>
#           Sebastian Heinlein <glatzor@ubuntu.com>
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License as
#  published by the Free Software Foundation; either version 2 of the
#  License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA 02111-1307
#  USA

from __future__ import absolute_import, print_function

import glob
import logging
import os.path
import re
import shutil
import time

from copy import copy

import apt_pkg
from .distinfo import DistInfo
from .distro import get_distro
#from apt_pkg import gettext as _


# some global helpers

__all__ = ['is_mirror', 'SourceEntry', 'NullMatcher', 'SourcesList',
           'SourceEntryMatcher']


def is_mirror(master_uri, compare_uri):
    """ check if the given add_url is idential or a mirror of orig_uri e.g.:
        master_uri = archive.ubuntu.com
        compare_uri = de.archive.ubuntu.com
        -> True
    """
    # remove traling spaces and "/"
    compare_uri = compare_uri.rstrip("/ ")
    master_uri = master_uri.rstrip("/ ")
    # uri is identical
    if compare_uri == master_uri:
        #print "Identical"
        return True
    # add uri is a master site and orig_uri has the from "XX.mastersite"
    # (e.g. de.archive.ubuntu.com)
    try:
        compare_srv = compare_uri.split("//")[1]
        master_srv = master_uri.split("//")[1]
        #print "%s == %s " % (add_srv, orig_srv)
    except IndexError:  # ok, somethings wrong here
        #print "IndexError"
        return False
    # remove the leading "<country>." (if any) and see if that helps
    if "." in compare_srv and \
           compare_srv[compare_srv.index(".") + 1:] == master_srv:
        #print "Mirror"
        return True
    return False


def uniq(s):
    """ simple and efficient way to return uniq collection

    This is not intended for use with a SourceList. It is provided
    for internal use only. It does not have a leading underscore to
    not break any old code that uses it; but it should not be used
    in new code (and is not listed in __all__)."""
    return list(set(s))


class SourceEntry(object):
    """ single sources.list entry """

    @classmethod
    def create_line(cls, uri, disabled=False, type=get_distro().binary_type,
                    dist=get_distro().codename, comps=[], architectures=[],
                    trusted=None, comment=None):
        """ Create a line from the given parts.

        The 'uri' parameter is mandatory; the rest will be filled with defaults
        if not set.
        """
        if type.startswith("#"):
            # backwards compatibility; please just use disabled param
            disabled = True
            type = type.lstrip("# ")

        hashmark = "# " if disabled else ""

        options = []
        if architectures:
            options += ["arch=%s" % ','.join(architectures)]
        if not trusted is None:
            trusted = "yes" if trusted else "no"
            options += ["trusted=%s" % trusted]
        options = " ".join(options)
        if options:
            options = " [%s]" % options

        comps = " ".join(comps)

        if comment and not comment.startswith("#"):
            comment = "#%s" % comment

        line = "{hashmark}{type}{options} {uri} {dist} {comps} {comment}"
        return line.format(hashmark=hashmark, type=type, options=options, uri=uri,
                           dist=dist, comps=comps, comment=comment or '').strip()

    def __init__(self, line, file=None):
        self.invalid = False         # is the source entry valid
        self.disabled = False        # is it disabled ('#' in front)
        self.type = ""               # what type (deb, deb-src)
        self.architectures = []      # architectures
        self.trusted = None          # Trusted
        self.uri = ""                # base-uri
        self.dist = ""               # distribution (dapper, edgy, etc)
        self.comps = []              # list of available componetns (may empty)
        self.comment = ""            # (optional) comment
        self.line = line             # the original sources.list line
        if file is None:
            file = apt_pkg.config.find_dir(
                "Dir::Etc") + apt_pkg.config.find("Dir::Etc::sourcelist")
        self.file = file             # the file that the entry is located in
        self.parse(line)
        self.template = None         # type DistInfo.Suite
        self.children = []

    def __eq__(self, other):
        """ equal operator for two sources.list entries """
        if self.invalid or other.invalid:
            return (self.invalid == other.invalid and
                    self.line == other.line)
        return (self.disabled == other.disabled and
                self.type == other.type and
                set(self.architectures) == set(other.architectures) and
                self.trusted == other.trusted and
                self.uri.rstrip('/') == other.uri.rstrip('/') and
                self.dist == other.dist and
                set(self.comps) == set(other.comps))

    def __copy__(self):
        """ Copy this SourceEntry """
        return SourceEntry(str(self), file=self.file)

    def _replace(self, **kwargs):
        """ Return copy of this SourceEntry with replaced field(s) """
        entry = copy(self)
        for (k, v) in kwargs.items():
            setattr(entry, k, v)
        return entry

    def mysplit(self, line):
        """ a split() implementation that understands the sources.list
            format better and takes [] into account (for e.g. cdroms) """
        line = line.strip()
        pieces = []
        tmp = ""
        # we are inside a [..] block
        p_found = False
        space_found = False
        for i in range(len(line)):
            if line[i] == "[":
                if space_found:
                    space_found = False
                    p_found = True
                    pieces.append(tmp)
                    tmp = line[i]
                else:
                    p_found = True
                    tmp += line[i]
            elif line[i] == "]":
                p_found = False
                tmp += line[i]
            elif space_found and not line[i].isspace():
                # we skip one or more space
                space_found = False
                pieces.append(tmp)
                tmp = line[i]
            elif line[i].isspace() and not p_found:
                # found a whitespace
                space_found = True
            else:
                tmp += line[i]
        # append last piece
        if len(tmp) > 0:
            pieces.append(tmp)
        return pieces

    def parse(self, line):
        """ parse a given sources.list (textual) line and break it up
            into the field we have """
        self.line = line
        line = line.strip()
        # check if the source is enabled/disabled
        if line == "" or line == "#":  # empty line
            self.invalid = True
            return
        if line[0] == "#":
            self.disabled = True
            pieces = line[1:].strip().split()
            # if it looks not like a disabled deb line return
            if not pieces[0] in ("rpm", "rpm-src", "deb", "deb-src"):
                self.invalid = True
                return
            else:
                line = line[1:]
        # check for another "#" in the line (this is treated as a comment)
        i = line.find("#")
        if i > 0:
            self.comment = line[i + 1:]
            line = line[:i]
        # source is ok, split it and see what we have
        pieces = self.mysplit(line)
        # Sanity check
        if len(pieces) < 3:
            self.invalid = True
            return
        # Type, deb or deb-src
        self.type = pieces[0].strip()
        # Sanity check
        if self.type not in ("deb", "deb-src", "rpm", "rpm-src"):
            self.invalid = True
            return

        if pieces[1].strip()[0] == "[":
            options = pieces.pop(1).strip("[]").split()
            for option in options:
                try:
                    key, value = option.split("=", 1)
                except Exception:
                    self.invalid = True
                else:
                    if key == "arch":
                        self.architectures = value.split(",")
                    elif key == "trusted":
                        self.trusted = apt_pkg.string_to_bool(value)
                    else:
                        self.invalid = True

        # URI
        self.uri = pieces[1].strip()
        if len(self.uri) < 1:
            self.invalid = True
        # distro and components (optional)
        # Directory or distro
        self.dist = pieces[2].strip()
        if len(pieces) > 3:
            # List of components
            self.comps = pieces[3:]
        else:
            self.comps = []

    def set_enabled(self, new_value):
        """ set a line to enabled or disabled """
        self.disabled = not new_value
        # enable, remove all "#" from the start of the line
        if new_value:
            self.line = self.line.lstrip().lstrip('#')
        else:
            # disabled, add a "#"
            if self.line.strip()[0] != "#":
                self.line = "#" + self.line

    def __str__(self):
        """ debug helper """
        return self.str().strip()

    def str(self):
        """ return the current entry as string """
        if self.invalid:
            return self.line
        line = self.create_line(disabled=self.disabled, type=self.type,
                                uri=self.uri, dist=self.dist, comps=self.comps,
                                architectures=self.architectures,
                                trusted=self.trusted, comment=self.comment)
        return "%s\n" % line


class NullMatcher(object):
    """ a Matcher that does nothing """

    def match(self, s):
        return True


class SourcesList(object):
    """ represents the full sources.list + sources.list.d file """

    def __init__(self,
                 withMatcher=True,
                 matcherPath="/usr/share/python-apt/templates/"):
        self.list = []          # the actual SourceEntries Type
        if withMatcher:
            self.matcher = SourceEntryMatcher(matcherPath)
        else:
            self.matcher = NullMatcher()
        self.refresh()

    def refresh(self):
        """ update the list of known entries """
        self.list = []
        # read sources.list
        file = apt_pkg.config.find_file("Dir::Etc::sourcelist")
        self.load(file)
        # read sources.list.d
        partsdir = apt_pkg.config.find_dir("Dir::Etc::sourceparts")
        for file in glob.glob("%s/*.list" % partsdir):
            self.load(file)
        # check if the source item fits a predefined template
        for source in self.list:
            if not source.invalid:
                self.matcher.match(source)

    def __iter__(self):
        """ simple iterator to go over self.list, returns SourceEntry
            types """
        for entry in self.list:
            yield entry

    def __find(self, *predicates, **attrs):
        uri = attrs.pop('uri', None)
        for source in self.list:
            if uri and uri.rstrip('/') != source.uri.rstrip('/'):
                continue
            if (all(getattr(source, key) == attrs[key] for key in attrs) and
                    all(predicate(source) for predicate in predicates)):
                yield source

    def __len__(self):
        """ calculate len of self.list """
        return len(self.list)

    def __eq__(self, other):
        """ equal operator for two sources.list entries """
        return all([e in other for e in self]) and all([e in self for e in other])

    def add(self, type, uri, dist, orig_comps, comment="", pos=-1, file=None,
            architectures=[]):
        """
        Add a new source to the sources.list.
        The method will search for existing matching repos and will try to
        reuse them as far as possible
        """

        type = type.strip()
        disabled = type.startswith("#")
        if disabled:
            type = type[1:].lstrip()
        architectures = set(architectures)
        # create a working copy of the component list so that
        # we can modify it later
        comps = orig_comps[:]
        sources = self.__find(lambda s: set(s.architectures) == architectures,
                              disabled=disabled, invalid=False, type=type,
                              uri=uri, dist=dist)
        # check if we have this source already in the sources.list
        for source in sources:
            for new_comp in comps:
                if new_comp in source.comps:
                    # we have this component already, delete it
                    # from the new_comps list
                    del comps[comps.index(new_comp)]
                    if len(comps) == 0:
                        return source

        sources = self.__find(lambda s: set(s.architectures) == architectures,
                              invalid=False, type=type, uri=uri, dist=dist)
        for source in sources:
            if source.disabled == disabled:
                # if there is a repo with the same (disabled, type, uri, dist)
                # just add the components
                if set(source.comps) != set(comps):
                    source.comps = uniq(source.comps + comps)
                return source
            elif source.disabled and not disabled:
                # enable any matching (type, uri, dist), but disabled repo
                if set(source.comps) == set(comps):
                    source.disabled = False
                    return source
        # there isn't any matching source, so create a new line and parse it
        parts = [
            "#" if disabled else "",
            type,
            ("[arch=%s]" % ",".join(architectures)) if architectures else "",
            uri,
            dist,
        ]
        parts.extend(comps)
        if comment:
            parts.append("#" + comment)
        line = " ".join(part for part in parts if part) + "\n"

        new_entry = SourceEntry(line)
        if file is not None:
            new_entry.file = file
        self.matcher.match(new_entry)
        if pos < 0:
            self.list.append(new_entry)
        else:
            self.list.insert(pos, new_entry)
        return new_entry

    def remove(self, source_entry):
        """ remove the specified entry from the sources.list """
        self.list.remove(source_entry)

    def restore_backup(self, backup_ext):
        " restore sources.list files based on the backup extension "
        file = apt_pkg.config.find_file("Dir::Etc::sourcelist")
        if os.path.exists(file + backup_ext) and os.path.exists(file):
            shutil.copy(file + backup_ext, file)
        # now sources.list.d
        partsdir = apt_pkg.config.find_dir("Dir::Etc::sourceparts")
        for file in glob.glob("%s/*.list" % partsdir):
            if os.path.exists(file + backup_ext):
                shutil.copy(file + backup_ext, file)

    def backup(self, backup_ext=None):
        """ make a backup of the current source files, if no backup extension
            is given, the current date/time is used (and returned) """
        already_backuped = set()
        if backup_ext is None:
            backup_ext = time.strftime("%y%m%d.%H%M")
        for source in self.list:
            if (source.file not in already_backuped and
                os.path.exists(source.file)):
                shutil.copy(source.file, "%s%s" % (source.file, backup_ext))
        return backup_ext

    def load(self, file):
        """ (re)load the current sources """
        try:
            with open(file, "r") as f:
                for line in f:
                    source = SourceEntry(line, file)
                    self.list.append(source)
        except Exception:
            logging.warning("could not open file '%s'\n" % file)

    def save(self):
        """ save the current sources """
        files = {}
        # write an empty default config file if there aren't any sources
        if len(self.list) == 0:
            path = apt_pkg.config.find_file("Dir::Etc::sourcelist")
            header = (
                "## See sources.list(5) for more information, especialy\n"
                "# Remember that you can only use http, ftp or file URIs\n"
                "# CDROMs are managed through the apt-cdrom tool.\n")

            with open(path, "w") as f:
                f.write(header)
            return

        try:
            for source in self.list:
                if source.file not in files:
                    files[source.file] = open(source.file, "w")
                files[source.file].write(source.str())
        finally:
            for f in files:
                files[f].close()

    def check_for_relations(self, sources_list):
        """get all parent and child channels in the sources list"""
        parents = []
        used_child_templates = {}
        for source in sources_list:
            # try to avoid checking uninterressting sources
            if source.template is None:
                continue
            # set up a dict with all used child templates and corresponding
            # source entries
            if source.template.child:
                key = source.template
                if key not in used_child_templates:
                    used_child_templates[key] = []
                temp = used_child_templates[key]
                temp.append(source)
            else:
                # store each source with children aka. a parent :)
                if len(source.template.children) > 0:
                    parents.append(source)
        #print self.used_child_templates
        #print self.parents
        return (parents, used_child_templates)


class CollapsedSourcesList(object):
    """ collapsed version of SourcesList

    This provides a 'collapsed' view of a SourcesList.
    Each entry in our list is a MergedSourceEntry, representing real
    SourceEntry(s) from our backing SourcesList.

    Any changes to our MergedSourceEntries are reflected in our
    backing SourcesList, however direct changes to SourceEntries
    in our backing SourcesList are not reflected in our list until
    after our refresh() method is called.
    """
    def __init__(self, sourceslist=None):
        self.sourceslist = sourceslist or SourcesList()
        self.list = []
        self.refresh()

    def __iter__(self):
        """ iterator for self.list

        Returns MergedSourceEntry objects
        """
        for entry in self.list:
            yield entry

    def __len__(self):
        """ calculate len of self.list """
        return len(self.list)

    def __eq__(self, other):
        """ equal operator for two sources.list entries """
        return all([e in other for e in self]) and all([e in self for e in other])

    def refresh(self):
        """ update only our list of MergedSourceEntries

        This updates only our list of MergedSourceEntries, our backing
        SourcesList is not updated.  This should be called anytime
        our backing SourcesList is updated directly.

        This does not refresh our backing SourcesList.
        """
        self.list = []
        for entry in self.sourceslist:
            for mergedentry in self.list:
                if mergedentry.match(entry):
                    mergedentry._append(entry)
                    break
            else:
                self.list.append(MergedSourceEntry(entry, self.sourceslist))

    def add_entry(self, new_entry, after=None, before=None):
        """ Add a new entry to the sources.list.

        This will try to find an existing entry, or an existing entry with
        the opposite 'disabled' state, to reuse.

        If an existing entry does not exist, new_entry is inserted.
        If either 'after' or 'before' are specified, and match an existing
        SourceEntry in our list, then new_entry will be inserted before
        or after the specified SourceEntry.  If both 'after' and 'before'
        are provided, 'after' has precedence.  If neither 'after' or 'before'
        are provided, new_entry is appended to the end of the list.
        """
        # the 'inverse' is just the entry with disabled field toggled
        # this is so we can correctly maintain the requested comps
        # for both the enabled and disabled entry matches
        inverse = new_entry._replace(disabled=not new_entry.disabled)

        # the list of comps is the same for new_entry and inverse
        comps = set(new_entry.comps)

        match_entry = None
        match_inverse = None
        for c in self.list:
            if c.match(new_entry):
                match_entry = c
            if c.match(inverse):
                match_inverse = c
            if match_entry and match_inverse:
                break

        if match_entry:
            # at least one existing entry
            if match_inverse:
                # remove comps from inverse
                inverse_comps = set(match_inverse.comps) - comps
                match_inverse.comps = list(inverse_comps)
            # add comps to existing entry
            return match_entry.get_entry(comps, add=True)

        if match_inverse:
            # at least one existing inverse entry, and no matching entry;
            # we want to replace the inverse entry and toggle its disabled state
            new_inverse = match_inverse.get_entry(comps, add=True, isolate=True)

            # after modifying the entry, we must refresh our merged entries
            new_inverse.set_enabled(new_inverse.disabled)
            self.refresh()
            return self.get_entry(new_entry)

        # no match at all: just append/insert new_entry
        if after and after in self.sourceslist.list:
            new_index = self.sourceslist.list.index(after) + 1
            self.sourceslist.list.insert(new_index, new_entry)
        elif before and before in self.sourceslist.list:
            new_index = self.sourceslist.list.index(before)
            self.sourceslist.list.insert(new_index, new_entry)
        else:
            self.sourceslist.list.append(new_entry)
        self.list.append(MergedSourceEntry(new_entry, self.sourceslist))
        return new_entry

    def remove_entry(self, entry):
        """ Remove the specified entry form the sources.list

        This removes as much as possible of the entry.  If the entry
        matches an existing entry in our list, but our entry contains
        more components, only the specified components will be removed
        from our list's entry.  Similarly, if entry contains multiple
        components, this will remove those components from one or multiple
        entries, if needed.

        Any entries in our list that have all their components removed will
        be removed from our list.
        """
        for c in self.list:
            if c.match(entry):
                c.comps = list(set(c.comps) - set(entry.comps))

    def get_entry(self, new_entry):
        """ If we already contain new_entry, find and return it

        If new_entry is already contained in our list, with at least
        all the components in new_entry, this returns our existing entry.
        The returned entry may have more components than new_entry.

        If new_entry is not contained in our list, or we do not
        have all the components in new_entry, this returns None.

        This may combine multiple existing SourceEntry lines into a
        single SourceEntry line so it contains all the requested
        components.
        """
        for c in self.list:
            if c.match(new_entry):
                return c.get_entry(new_entry.comps)
        return None

    def has_entry(self, new_entry):
        """ Check if we already contain new_entry

        If new_entry contains multiple components, they may be located
        in multiple lines; this only checks that all requested components,
        for exactly the SourceEntry that equals new_entry (besides comps),
        are included in our list.

        This will not change our list.
        """
        for c in self.list:
            if c.match(new_entry):
                return set(c.comps) >= set(new_entry.comps)
        return False


class SourceEntryMatcher(object):
    """ matcher class to make a source entry look nice
        lots of predefined matchers to make it i18n/gettext friendly
        """

    def __init__(self, matcherPath):
        self.templates = []
        # Get the human readable channel and comp names from the channel .infos
        spec_files = glob.glob("%s/*.info" % matcherPath)
        for f in spec_files:
            f = os.path.basename(f)
            i = f.find(".info")
            f = f[0:i]
            dist = DistInfo(f, base_dir=matcherPath)
            for template in dist.templates:
                if template.match_uri is not None:
                    self.templates.append(template)
        return

    def match(self, source):
        """Add a matching template to the source"""
        found = False
        for template in self.templates:
            if (re.search(template.match_uri, source.uri) and
                    re.match(template.match_name, source.dist) and
                    # deb is a valid fallback for deb-src (if that is not
                    # definied, see #760035
                    (source.type == template.type or template.type == "deb")):
                found = True
                source.template = template
                break
            elif (template.is_mirror(source.uri) and
                      re.match(template.match_name, source.dist)):
                found = True
                source.template = template
                break
        return found


# some simple tests
if __name__ == "__main__":
    apt_pkg.init_config()
    sources = SourcesList()

    for entry in sources:
        logging.info("entry %s" % entry.str())
        #print entry.uri

    mirror = is_mirror("http://archive.ubuntu.com/ubuntu/",
                       "http://de.archive.ubuntu.com/ubuntu/")
    logging.info("is_mirror(): %s" % mirror)

    logging.info(is_mirror("http://archive.ubuntu.com/ubuntu",
                    "http://de.archive.ubuntu.com/ubuntu/"))
    logging.info(is_mirror("http://archive.ubuntu.com/ubuntu/",
                    "http://de.archive.ubuntu.com/ubuntu"))
