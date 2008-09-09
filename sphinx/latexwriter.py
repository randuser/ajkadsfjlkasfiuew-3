# -*- coding: utf-8 -*-
"""
    sphinx.latexwriter
    ~~~~~~~~~~~~~~~~~~

    Custom docutils writer for LaTeX.

    Much of this code is adapted from Dave Kuhlman's "docpy" writer from his
    docutils sandbox.

    :copyright: 2007-2008 by Georg Brandl, Dave Kuhlman.
    :license: BSD.
"""

import re
import sys
import time
from os import path

from docutils import nodes, writers
from docutils.writers.latex2e import Babel

from sphinx import addnodes
from sphinx import highlighting
from sphinx.locale import admonitionlabels, versionlabels
from sphinx.util.texescape import tex_escape_map
from sphinx.util.smartypants import educateQuotesLatex

HEADER = r'''%% Generated by Sphinx.
\documentclass[%(papersize)s,%(pointsize)s%(classoptions)s]{%(docclass)s}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{babel}
\title{%(title)s}
\date{%(date)s}
\release{%(release)s}
\author{%(author)s}
\newcommand{\sphinxlogo}{%(logo)s}
\renewcommand{\releasename}{%(releasename)s}
%(preamble)s
\makeindex
'''

BEGIN_DOC = r'''
\begin{document}
%(shorthandoff)s
\maketitle
\tableofcontents
'''

FOOTER = r'''
\printindex
\end{document}
'''

GRAPHICX = r'''
%% Check if we are compiling under latex or pdflatex.
\ifx\pdftexversion\undefined
  \usepackage{graphicx}
\else
  \usepackage[pdftex]{graphicx}
\fi
'''


class LaTeXWriter(writers.Writer):

    supported = ('sphinxlatex',)

    settings_spec = ('LaTeX writer options', '', (
        ('Document name', ['--docname'], {'default': ''}),
        ('Document class', ['--docclass'], {'default': 'manual'}),
        ('Author', ['--author'], {'default': ''}),
        ))
    settings_defaults = {}

    output = None

    def __init__(self, builder):
        writers.Writer.__init__(self)
        self.builder = builder

    def translate(self):
        visitor = LaTeXTranslator(self.document, self.builder)
        self.document.walkabout(visitor)
        self.output = visitor.astext()


# Helper classes

class ExtBabel(Babel):
    def get_shorthandoff(self):
        if self.language == 'de':
            return '\\shorthandoff{"}'
        return ''


class Table(object):
    def __init__(self):
        self.col = 0
        self.colcount = 0
        self.colspec = None
        self.had_head = False
        self.has_verbatim = False


class Desc(object):
    def __init__(self, node):
        self.env = LaTeXTranslator.desc_map.get(node['desctype'], 'describe')
        self.ni = node['noindex']
        self.type = self.cls = self.name = self.params = self.annotation = ''
        self.count = 0


class LaTeXTranslator(nodes.NodeVisitor):
    sectionnames = ["part", "chapter", "section", "subsection",
                    "subsubsection", "paragraph", "subparagraph"]

    ignore_missing_images = False

    def __init__(self, document, builder):
        nodes.NodeVisitor.__init__(self, document)
        self.builder = builder
        self.body = []
        docclass = document.settings.docclass
        paper = builder.config.latex_paper_size + 'paper'
        if paper == 'paper': # e.g. command line "-D latex_paper_size="
            paper = 'letterpaper'
        date = time.strftime(builder.config.today_fmt or _('%B %d, %Y'))
        logo = (builder.config.latex_logo and
                '\\includegraphics{%s}\\par' % path.basename(builder.config.latex_logo)
                or '')
        self.options = {'docclass': docclass,
                        'papersize': paper,
                        'pointsize': builder.config.latex_font_size,
                        'preamble': builder.config.latex_preamble,
                        'modindex': builder.config.latex_use_modindex,
                        'author': document.settings.author,
                        'docname': document.settings.docname,
                        # if empty, the title is set to the first section title
                        'title': document.settings.title,
                        'release': builder.config.release,
                        'releasename': _('Release'),
                        'logo': logo,
                        'date': date,
                        'classoptions': ',english',
                        'shorthandoff': '',
                        }
        if builder.config.language:
            babel = ExtBabel(builder.config.language)
            self.options['classoptions'] += ',' + babel.get_language()
            self.shorthandoff = babel.get_shorthandoff()
        self.highlighter = highlighting.PygmentsBridge(
            'latex', builder.config.pygments_style)
        self.context = []
        self.descstack = []
        self.bibitems = []
        self.table = None
        self.next_table_colspec = None
        self.highlightlang = builder.config.highlight_language
        self.highlightlinenothreshold = sys.maxint
        self.written_ids = set()
        if docclass == 'manual':
            if builder.config.latex_use_parts:
                self.top_sectionlevel = 0
            else:
                self.top_sectionlevel = 1
        else:
            self.top_sectionlevel = 2
        self.next_section_target = None
        # flags
        self.verbatim = None
        self.in_title = 0
        self.in_production_list = 0
        self.first_document = 1
        self.this_is_the_title = 1
        self.literal_whitespace = 0
        self.need_graphicx = 0

    def astext(self):
        return (HEADER % self.options) + \
               (self.options['modindex'] and '\\makemodindex\n' or '') + \
               self.highlighter.get_stylesheet() + \
               (self.need_graphicx and GRAPHICX or '') + \
               '\n\n' + \
               u''.join(self.body) + \
               (self.options['modindex'] and
                ('\\renewcommand{\\indexname}{%s}' % _('Module index') +
                '\\printmodindex' +
                '\\renewcommand{\\indexname}{%s}\n' % _('Index')) or '') + \
               (FOOTER % self.options)

    def visit_document(self, node):
        if self.first_document == 1:
            # the first document is all the regular content ...
            self.body.append(BEGIN_DOC)
            self.first_document = 0
        elif self.first_document == 0:
            # ... and all others are the appendices
            self.body.append('\n\\appendix\n')
            self.first_document = -1
        # "- 1" because the level is increased before the title is visited
        self.sectionlevel = self.top_sectionlevel - 1
    def depart_document(self, node):
        if self.bibitems:
            widest_label = ""
            for bi in self.bibitems:
                if len(widest_label) < len(bi[0]):
                    widest_label = bi[0]
            self.body.append('\n\\begin{thebibliography}{%s}\n' % widest_label)
            for bi in self.bibitems:
                # cite_key: underscores must not be escaped
                cite_key = bi[0].replace(r"\_", "_")
                self.body.append('\\bibitem[%s]{%s}{%s}\n' % (bi[0], cite_key, bi[1]))
            self.body.append('\\end{thebibliography}\n')
            self.bibitems = []

    def visit_start_of_file(self, node):
        # This marks the begin of a new file; therefore the current module and
        # class must be reset
        self.body.append('\n\\resetcurrentobjects\n')
        raise nodes.SkipNode

    def visit_highlightlang(self, node):
        self.highlightlang = node['lang']
        self.highlightlinenothreshold = node['linenothreshold']
        raise nodes.SkipNode

    def visit_section(self, node):
        if not self.this_is_the_title:
            self.sectionlevel += 1
        self.body.append('\n\n')
        if self.next_section_target:
            self.body.append(r'\hypertarget{%s}{}' % self.next_section_target)
            self.next_section_target = None
        #if node.get('ids'):
        #    for id in node['ids']:
        #        if id not in self.written_ids:
        #            self.body.append(r'\hypertarget{%s}{}' % id)
        #            self.written_ids.add(id)
    def depart_section(self, node):
        self.sectionlevel = max(self.sectionlevel - 1, self.top_sectionlevel - 1)

    def visit_problematic(self, node):
        self.body.append(r'{\color{red}\bfseries{}')
    def depart_problematic(self, node):
        self.body.append('}')

    def visit_topic(self, node):
        self.body.append('\\setbox0\\vbox{\n'
                         '\\begin{minipage}{0.95\\textwidth}\n')
    def depart_topic(self, node):
        self.body.append('\\end{minipage}}\n'
                         '\\begin{center}\\setlength{\\fboxsep}{5pt}'
                         '\\shadowbox{\\box0}\\end{center}\n')
    visit_sidebar = visit_topic
    depart_sidebar = depart_topic

    def visit_glossary(self, node):
        pass
    def depart_glossary(self, node):
        pass

    def visit_productionlist(self, node):
        self.body.append('\n\n\\begin{productionlist}\n')
        self.in_production_list = 1
    def depart_productionlist(self, node):
        self.body.append('\\end{productionlist}\n\n')
        self.in_production_list = 0

    def visit_production(self, node):
        if node['tokenname']:
            self.body.append('\\production{%s}{' % self.encode(node['tokenname']))
        else:
            self.body.append('\\productioncont{')
    def depart_production(self, node):
        self.body.append('}\n')

    def visit_transition(self, node):
        self.body.append('\n\n\\bigskip\\hrule{}\\bigskip\n\n')
    def depart_transition(self, node):
        pass

    def visit_title(self, node):
        if isinstance(node.parent, addnodes.seealso):
            # the environment already handles this
            raise nodes.SkipNode
        elif self.this_is_the_title:
            if len(node.children) != 1 and not isinstance(node.children[0], nodes.Text):
                self.builder.warn('document title is not a single Text node')
            if not self.options['title']:
                self.options['title'] = node.astext()
            self.this_is_the_title = 0
            raise nodes.SkipNode
        elif isinstance(node.parent, nodes.section):
            self.body.append(r'\%s{' % self.sectionnames[self.sectionlevel])
            self.context.append('}\n')
        elif isinstance(node.parent, (nodes.topic, nodes.sidebar, nodes.admonition)):
            self.body.append(r'\textbf{')
            self.context.append('}\n\n\medskip\n\n')
        else:
            self.builder.warn('encountered title node not in section, topic, admonition'
                              ' or sidebar')
            self.body.append('\\textbf{')
            self.context.append('}')
        self.in_title = 1
    def depart_title(self, node):
        self.in_title = 0
        self.body.append(self.context.pop())

    desc_map = {
        'function' : 'funcdesc',
        'class': 'classdesc',
        'method': 'methoddesc',
        'staticmethod': 'staticmethoddesc',
        'exception': 'excdesc',
        'data': 'datadesc',
        'attribute': 'memberdesc',
        'opcode': 'opcodedesc',

        'cfunction': 'cfuncdesc',
        'cmember': 'cmemberdesc',
        'cmacro': 'csimplemacrodesc',
        'ctype': 'ctypedesc',
        'cvar': 'cvardesc',

        'describe': 'describe',
        # and all others are 'describe' too
    }

    def visit_desc(self, node):
        self.descstack.append(Desc(node))
    def depart_desc(self, node):
        d = self.descstack.pop()
        self.body.append("\\end{%s%s}\n" % (d.env, d.ni and 'ni' or ''))

    def visit_desc_signature(self, node):
        d = self.descstack[-1]
        # reset these for every signature
        d.type = d.cls = d.name = d.params = ''
    def depart_desc_signature(self, node):
        d = self.descstack[-1]
        d.cls = d.cls.rstrip('.')
        if node.parent['desctype'] != 'describe' and node['ids']:
            hyper = '\\hypertarget{%s}{}' % node['ids'][0]
        else:
            hyper = ''
        if d.count == 0:
            t1 = "\n\n%s\\begin{%s%s}" % (hyper, d.env, (d.ni and 'ni' or ''))
        else:
            t1 = "\n%s\\%sline%s" % (hyper, d.env[:-4], (d.ni and 'ni' or ''))
        d.count += 1
        if d.env in ('funcdesc', 'classdesc', 'excclassdesc'):
            t2 = "{%s}{%s}" % (d.name, d.params)
        elif d.env in ('datadesc', 'classdesc*', 'excdesc', 'csimplemacrodesc'):
            t2 = "{%s}" % (d.name)
        elif d.env in ('methoddesc', 'staticmethoddesc'):
            if d.cls:
                t2 = "[%s]{%s}{%s}" % (d.cls, d.name, d.params)
            else:
                t2 = "{%s}{%s}" % (d.name, d.params)
        elif d.env == 'memberdesc':
            if d.cls:
                t2 = "[%s]{%s}" % (d.cls, d.name)
            else:
                t2 = "{%s}" % d.name
        elif d.env == 'cfuncdesc':
            if d.cls:
                # C++ class names
                d.name = '%s::%s' % (d.cls, d.name)
            t2 = "{%s}{%s}{%s}" % (d.type, d.name, d.params)
        elif d.env == 'cmemberdesc':
            try:
                type, container = d.type.rsplit(' ', 1)
                container = container.rstrip('.')
            except ValueError:
                container = ''
                type = d.type
            t2 = "{%s}{%s}{%s}" % (container, type, d.name)
        elif d.env == 'cvardesc':
            t2 = "{%s}{%s}" % (d.type, d.name)
        elif d.env == 'ctypedesc':
            t2 = "{%s}" % (d.name)
        elif d.env == 'opcodedesc':
            t2 = "{%s}{%s}" % (d.name, d.params)
        elif d.env == 'describe':
            t2 = "{%s}" % d.name
        self.body.append(t1 + t2)

    def visit_desc_type(self, node):
        d = self.descstack[-1]
        if d.env == 'describe':
            d.name += self.encode(node.astext())
        else:
            self.descstack[-1].type = self.encode(node.astext().strip())
        raise nodes.SkipNode

    def visit_desc_name(self, node):
        d = self.descstack[-1]
        if d.env == 'describe':
            d.name += self.encode(node.astext())
        else:
            self.descstack[-1].name = self.encode(node.astext().strip())
        raise nodes.SkipNode

    def visit_desc_addname(self, node):
        d = self.descstack[-1]
        if d.env == 'describe':
            d.name += self.encode(node.astext())
        else:
            self.descstack[-1].cls = self.encode(node.astext().strip())
        raise nodes.SkipNode

    def visit_desc_parameterlist(self, node):
        d = self.descstack[-1]
        if d.env == 'describe':
            d.name += self.encode(node.astext())
        else:
            self.descstack[-1].params = self.encode(node.astext().strip())
        raise nodes.SkipNode

    def visit_desc_annotation(self, node):
        d = self.descstack[-1]
        if d.env == 'describe':
            d.name += self.encode(node.astext())
        else:
            self.descstack[-1].annotation = self.encode(node.astext().strip())
        raise nodes.SkipNode

    def visit_refcount(self, node):
        self.body.append("\\emph{")
    def depart_refcount(self, node):
        self.body.append("}\\\\")

    def visit_desc_content(self, node):
        if node.children and isinstance(node.children[0], addnodes.desc):
            # avoid empty desc environment which causes a formatting bug
            self.body.append('~')
    def depart_desc_content(self, node):
        pass

    def visit_seealso(self, node):
        self.body.append("\n\n\\strong{%s:}\n\n" % admonitionlabels['seealso'])
    def depart_seealso(self, node):
        self.body.append("\n\n")

    def visit_rubric(self, node):
        if len(node.children) == 1 and node.children[0].astext() == 'Footnotes':
            raise nodes.SkipNode
        self.body.append('\\paragraph{')
        self.context.append('}\n')
    def depart_rubric(self, node):
        self.body.append(self.context.pop())

    def visit_footnote(self, node):
        # XXX not optimal, footnotes are at section end
        num = node.children[0].astext().strip()
        self.body.append('\\footnotetext[%s]{' % num)
    def depart_footnote(self, node):
        self.body.append('}')

    def visit_label(self, node):
        if isinstance(node.parent, nodes.citation):
            self.bibitems[-1][0] = node.astext()
        raise nodes.SkipNode

    def visit_tabular_col_spec(self, node):
        self.next_table_colspec = node['spec']
        raise nodes.SkipNode

    def visit_table(self, node):
        if self.table:
            raise NotImplementedError('Nested tables are not supported.')
        self.table = Table()
        self.tablebody = []
        # Redirect body output until table is finished.
        self._body = self.body
        self.body = self.tablebody
    def depart_table(self, node):
        self.body = self._body
        if self.table.has_verbatim:
            self.body.append('\n\\begin{tabular}')
        else:
            self.body.append('\n\\begin{tabulary}{\\textwidth}')
        if self.table.colspec:
            self.body.append(self.table.colspec)
        else:
            if self.table.has_verbatim:
                colwidth = 0.95 / self.table.colcount
                colspec = ('p{%.3f\\textwidth}|' % colwidth) * self.table.colcount
                self.body.append('{|' + colspec + '}\n')
            else:
                self.body.append('{|' + ('L|' * self.table.colcount) + '}\n')
        self.body.extend(self.tablebody)
        if self.table.has_verbatim:
            self.body.append('\\end{tabular}\n\n')
        else:
            self.body.append('\\end{tabulary}\n\n')
        self.table = None
        self.tablebody = None

    def visit_colspec(self, node):
        self.table.colcount += 1
    def depart_colspec(self, node):
        pass

    def visit_tgroup(self, node):
        pass
    def depart_tgroup(self, node):
        pass

    def visit_thead(self, node):
        if self.next_table_colspec:
            self.table.colspec = '{%s}\n' % self.next_table_colspec
        self.next_table_colspec = None
        self.body.append('\\hline\n')
        self.table.had_head = True
    def depart_thead(self, node):
        self.body.append('\\hline\n')

    def visit_tbody(self, node):
        if not self.table.had_head:
            self.visit_thead(node)
    def depart_tbody(self, node):
        self.body.append('\\hline\n')

    def visit_row(self, node):
        self.table.col = 0
    def depart_row(self, node):
        self.body.append('\\\\\n')

    def visit_entry(self, node):
        if node.has_key('morerows') or node.has_key('morecols'):
            raise NotImplementedError('Column or row spanning cells are '
                                      'not implemented.')
        if self.table.col > 0:
            self.body.append(' & ')
        self.table.col += 1
        if isinstance(node.parent.parent, nodes.thead):
            self.body.append('\\textbf{')
            self.context.append('}')
        else:
            self.context.append('')
    def depart_entry(self, node):
        self.body.append(self.context.pop()) # header

    def visit_acks(self, node):
        # this is a list in the source, but should be rendered as a
        # comma-separated list here
        self.body.append('\n\n')
        self.body.append(', '.join(n.astext() for n in node.children[0].children) + '.')
        self.body.append('\n\n')
        raise nodes.SkipNode

    def visit_bullet_list(self, node):
        self.body.append('\\begin{itemize}\n' )
    def depart_bullet_list(self, node):
        self.body.append('\\end{itemize}\n' )

    def visit_enumerated_list(self, node):
        self.body.append('\\begin{enumerate}\n' )
    def depart_enumerated_list(self, node):
        self.body.append('\\end{enumerate}\n' )

    def visit_list_item(self, node):
        # Append "{}" in case the next character is "[", which would break
        # LaTeX's list environment (no numbering and the "[" is not printed).
        self.body.append(r'\item {} ')
    def depart_list_item(self, node):
        self.body.append('\n')

    def visit_definition_list(self, node):
        self.body.append('\\begin{description}\n')
    def depart_definition_list(self, node):
        self.body.append('\\end{description}\n')

    def visit_definition_list_item(self, node):
        pass
    def depart_definition_list_item(self, node):
        pass

    def visit_term(self, node):
        ctx = ']'
        if node.has_key('ids') and node['ids']:
            ctx += '\\hypertarget{%s}{}' % node['ids'][0]
        self.body.append('\\item[')
        self.context.append(ctx)
    def depart_term(self, node):
        self.body.append(self.context.pop())

    def visit_classifier(self, node):
        self.body.append('{[}')
    def depart_classifier(self, node):
        self.body.append('{]}')

    def visit_definition(self, node):
        pass
    def depart_definition(self, node):
        self.body.append('\n')

    def visit_field_list(self, node):
        self.body.append('\\begin{quote}\\begin{description}\n')
    def depart_field_list(self, node):
        self.body.append('\\end{description}\\end{quote}\n')

    def visit_field(self, node):
        pass
    def depart_field(self, node):
        pass

    visit_field_name = visit_term
    depart_field_name = depart_term

    visit_field_body = visit_definition
    depart_field_body = depart_definition

    def visit_paragraph(self, node):
        self.body.append('\n')
    def depart_paragraph(self, node):
        self.body.append('\n')

    def visit_centered(self, node):
        self.body.append('\n\\begin{centering}')
    def depart_centered(self, node):
        self.body.append('\n\\end{centering}')

    def visit_module(self, node):
        modname = node['modname']
        self.body.append('\n\\declaremodule[%s]{}{%s}' % (modname.replace('_', ''),
                                                          self.encode(modname)))
        self.body.append('\n\\modulesynopsis{%s}' % self.encode(node['synopsis']))
        if node.has_key('platform'):
            self.body.append('\\platform{%s}' % self.encode(node['platform']))
    def depart_module(self, node):
        pass

    def latex_image_length(self, width_str):
        match = re.match('(\d*\.?\d*)\s*(\S*)', width_str)
        if not match:
            # fallback
            return width_str
        res = width_str
        amount, unit = match.groups()[:2]
        if unit == "px":
            # LaTeX does not know pixels but points
            res = "%spt" % amount
        elif unit == "%":
            res = "%.3f\\linewidth" % (float(amount) / 100.0)
        return res

    def visit_image(self, node):
        self.need_graphicx = 1
        attrs = node.attributes
        pre = []                        # in reverse order
        post = []
        include_graphics_options = []
        inline = isinstance(node.parent, nodes.TextElement)
        if attrs.has_key('scale'):
            # Could also be done with ``scale`` option to
            # ``\includegraphics``; doing it this way for consistency.
            pre.append('\\scalebox{%f}{' % (attrs['scale'] / 100.0,))
            post.append('}')
        if attrs.has_key('width'):
            include_graphics_options.append('width=%s' % (
                            self.latex_image_length(attrs['width']), ))
        if attrs.has_key('height'):
            include_graphics_options.append('height=%s' % (
                            self.latex_image_length(attrs['height']), ))
        if attrs.has_key('align'):
            align_prepost = {
                # By default latex aligns the top of an image.
                (1, 'top'): ('', ''),
                (1, 'middle'): ('\\raisebox{-0.5\\height}{', '}'),
                (1, 'bottom'): ('\\raisebox{-\\height}{', '}'),
                (0, 'center'): ('{\\hfill', '\\hfill}'),
                # These 2 don't exactly do the right thing.  The image should
                # be floated alongside the paragraph.  See
                # http://www.w3.org/TR/html4/struct/objects.html#adef-align-IMG
                (0, 'left'): ('{', '\\hfill}'),
                (0, 'right'): ('{\\hfill', '}'),}
            try:
                pre.append(align_prepost[inline, attrs['align']][0])
                post.append(align_prepost[inline, attrs['align']][1])
            except KeyError:
                pass                    # XXX complain here?
        if not inline:
            pre.append('\n')
            post.append('\n')
        pre.reverse()
        if node['uri'] in self.builder.images:
            uri = self.builder.images[node['uri']]
        else:
            # missing image!
            if self.ignore_missing_images:
                return
            uri = node['uri']
        if uri.find('://') != -1:
            # ignore remote images
            return
        self.body.extend(pre)
        options = ''
        if include_graphics_options:
            options = '[%s]' % ','.join(include_graphics_options)
        self.body.append('\\includegraphics%s{%s}' % (options, uri))
        self.body.extend(post)
    def depart_image(self, node):
        pass

    def visit_figure(self, node):
        if (not node.attributes.has_key('align') or
            node.attributes['align'] == 'center'):
            # centering does not add vertical space like center.
            align = '\n\\centering'
            align_end = ''
        else:
            # TODO non vertical space for other alignments.
            align = '\\begin{flush%s}' % node.attributes['align']
            align_end = '\\end{flush%s}' % node.attributes['align']
        self.body.append('\\begin{figure}[htbp]%s\n' % align)
        self.context.append('%s\\end{figure}\n' % align_end)
    def depart_figure(self, node):
        self.body.append(self.context.pop())

    def visit_caption(self, node):
        self.body.append('\\caption{')
    def depart_caption(self, node):
        self.body.append('}')

    def visit_legend(self, node):
        self.body.append('{\\small ')
    def depart_legend(self, node):
        self.body.append('}')

    def visit_admonition(self, node):
        self.body.append('\n\\begin{quote}')
    def depart_admonition(self, node):
        self.body.append('\\end{quote}\n')

    def _make_visit_admonition(name):
        def visit_admonition(self, node):
            self.body.append('\n\\begin{notice}{%s}{%s:}' %
                             (name, admonitionlabels[name]))
        return visit_admonition
    def _depart_named_admonition(self, node):
        self.body.append('\\end{notice}\n')

    visit_attention = _make_visit_admonition('attention')
    depart_attention = _depart_named_admonition
    visit_caution = _make_visit_admonition('caution')
    depart_caution = _depart_named_admonition
    visit_danger = _make_visit_admonition('danger')
    depart_danger = _depart_named_admonition
    visit_error = _make_visit_admonition('error')
    depart_error = _depart_named_admonition
    visit_hint = _make_visit_admonition('hint')
    depart_hint = _depart_named_admonition
    visit_important = _make_visit_admonition('important')
    depart_important = _depart_named_admonition
    visit_note = _make_visit_admonition('note')
    depart_note = _depart_named_admonition
    visit_tip = _make_visit_admonition('tip')
    depart_tip = _depart_named_admonition
    visit_warning = _make_visit_admonition('warning')
    depart_warning = _depart_named_admonition

    def visit_versionmodified(self, node):
        intro = versionlabels[node['type']] % node['version']
        if node.children:
            intro += ': '
        else:
            intro += '.'
        self.body.append(intro)
    def depart_versionmodified(self, node):
        pass

    def visit_target(self, node):
        def add_target(id):
            # indexing uses standard LaTeX index markup, so the targets
            # will be generated differently
            if not id.startswith('index-'):
                self.body.append(r'\hypertarget{%s}{}' % id)

        if node.has_key('refid') and node['refid'] not in self.written_ids:
            parindex = node.parent.index(node)
            try:
                next = node.parent[parindex+1]
                if isinstance(next, nodes.section):
                    self.next_section_target = node['refid']
                    return
            except IndexError:
                pass
            add_target(node['refid'])
            self.written_ids.add(node['refid'])
    def depart_target(self, node):
        pass

    def visit_attribution(self, node):
        self.body.append('\n\\begin{flushright}\n')
        self.body.append('---')
    def depart_attribution(self, node):
        self.body.append('\n\\end{flushright}\n')

    def visit_index(self, node, scre=re.compile(r';\s*')):
        entries = node['entries']
        for type, string, tid, _ in entries:
            if type == 'single':
                self.body.append(r'\index{%s}' % scre.sub('!', self.encode(string)))
            elif type == 'pair':
                parts = tuple(self.encode(x.strip()) for x in string.split(';', 1))
                self.body.append(r'\indexii{%s}{%s}' % parts)
            elif type == 'triple':
                parts = tuple(self.encode(x.strip()) for x in string.split(';', 2))
                self.body.append(r'\indexiii{%s}{%s}{%s}' % parts)
            else:
                self.builder.warn('unknown index entry type %s found' % type)
        raise nodes.SkipNode

    def visit_raw(self, node):
        if 'latex' in node.get('format', '').split():
            self.body.append(node.astext())
        raise nodes.SkipNode

    def visit_reference(self, node):
        uri = node.get('refuri', '')
        if self.in_title or not uri:
            self.context.append('')
        elif uri.startswith('mailto:') or uri.startswith('http:') or \
             uri.startswith('ftp:'):
            self.body.append('\\href{%s}{' % self.encode(uri))
            self.context.append('}')
        elif uri.startswith('#'):
            self.body.append('\\hyperlink{%s}{' % uri[1:])
            self.context.append('}')
        elif uri.startswith('@token'):
            if self.in_production_list:
                self.body.append('\\token{')
            else:
                self.body.append('\\grammartoken{')
            self.context.append('}')
        else:
            self.builder.warn('unusable reference target found: %s' % uri)
            self.context.append('')
    def depart_reference(self, node):
        self.body.append(self.context.pop())

    def visit_pending_xref(self, node):
        pass
    def depart_pending_xref(self, node):
        pass

    def visit_emphasis(self, node):
        self.body.append(r'\emph{')
    def depart_emphasis(self, node):
        self.body.append('}')

    def visit_literal_emphasis(self, node):
        self.body.append(r'\emph{\texttt{')
    def depart_literal_emphasis(self, node):
        self.body.append('}}')

    def visit_strong(self, node):
        self.body.append(r'\textbf{')
    def depart_strong(self, node):
        self.body.append('}')

    def visit_title_reference(self, node):
        self.body.append(r'\emph{')
    def depart_title_reference(self, node):
        self.body.append('}')

    def visit_citation(self, node):
        # TODO maybe use cite bibitems
        self.bibitems.append(['', ''])
        self.context.append(len(self.body))
    def depart_citation(self, node):
        size = self.context.pop()
        text = ''.join(self.body[size:])
        del self.body[size:]
        self.bibitems[-1][1] = text

    def visit_citation_reference(self, node):
        citeid = node.astext()
        self.body.append('\\cite{%s}' % citeid)
        raise nodes.SkipNode

    def visit_literal(self, node):
        content = self.encode(node.astext().strip())
        if self.in_title:
            self.body.append(r'\texttt{%s}' % content)
        elif node.has_key('role') and node['role'] == 'samp':
            self.body.append(r'\samp{%s}' % content)
        else:
            self.body.append(r'\code{%s}' % content)
        raise nodes.SkipNode

    def visit_footnote_reference(self, node):
        self.body.append('\\footnotemark[%s]' % node.astext())
        raise nodes.SkipNode

    def visit_literal_block(self, node):
        self.verbatim = ''
    def depart_literal_block(self, node):
        code = self.verbatim.rstrip('\n')
        lang = self.highlightlang
        linenos = code.count('\n') >= self.highlightlinenothreshold - 1
        if node.has_key('language'):
            # code-block directives
            lang = node['language']
        if node.has_key('linenos'):
            linenos = node['linenos']
        hlcode = self.highlighter.highlight_block(code, lang, linenos)
        # workaround for Unicode issue
        hlcode = hlcode.replace(u'€', u'@texteuro[]')
        # must use original Verbatim environment and "tabular" environment
        if self.table:
            hlcode = hlcode.replace('\\begin{Verbatim}',
                                    '\\begin{OriginalVerbatim}')
            self.table.has_verbatim = True
        # get consistent trailer
        hlcode = hlcode.rstrip()[:-14] # strip \end{Verbatim}
        hlcode = hlcode.rstrip() + '\n'
        self.body.append('\n' + hlcode + '\\end{%sVerbatim}\n' %
                         (self.table and 'Original' or ''))
        self.verbatim = None
    visit_doctest_block = visit_literal_block
    depart_doctest_block = depart_literal_block

    def visit_line_block(self, node):
        """line-block:
        * whitespace (including linebreaks) is significant
        * inline markup is supported.
        * serif typeface
        """
        self.body.append('{\\raggedright{}')
        self.literal_whitespace = 1
    def depart_line_block(self, node):
        self.literal_whitespace = 0
        # remove the last \\
        del self.body[-1]
        self.body.append('}\n')

    def visit_line(self, node):
        self._line_start = len(self.body)
    def depart_line(self, node):
        if self._line_start == len(self.body):
            # no output in this line -- add a nonbreaking space, else the
            # \\ command will give an error
            self.body.append('~')
        self.body.append('\\\\\n')

    def visit_block_quote(self, node):
        # If the block quote contains a single object and that object
        # is a list, then generate a list not a block quote.
        # This lets us indent lists.
        done = 0
        if len(node.children) == 1:
            child = node.children[0]
            if isinstance(child, nodes.bullet_list) or \
                    isinstance(child, nodes.enumerated_list):
                done = 1
        if not done:
            self.body.append('\\begin{quote}\n')
    def depart_block_quote(self, node):
        done = 0
        if len(node.children) == 1:
            child = node.children[0]
            if isinstance(child, nodes.bullet_list) or \
                    isinstance(child, nodes.enumerated_list):
                done = 1
        if not done:
            self.body.append('\\end{quote}\n')

    # option node handling copied from docutils' latex writer

    def visit_option(self, node):
        if self.context[-1]:
            # this is not the first option
            self.body.append(', ')
    def depart_option(self, node):
        # flag that the first option is done.
        self.context[-1] += 1

    def visit_option_argument(self, node):
        """The delimiter betweeen an option and its argument."""
        self.body.append(node.get('delimiter', ' '))
    def depart_option_argument(self, node):
        pass

    def visit_option_group(self, node):
        self.body.append('\\item [')
        # flag for first option
        self.context.append(0)
    def depart_option_group(self, node):
        self.context.pop() # the flag
        self.body.append('] ')

    def visit_option_list(self, node):
        self.body.append('\\begin{optionlist}{3cm}\n')
    def depart_option_list(self, node):
        self.body.append('\\end{optionlist}\n')

    def visit_option_list_item(self, node):
        pass
    def depart_option_list_item(self, node):
        pass

    def visit_option_string(self, node):
        pass
    def depart_option_string(self, node):
        pass

    def visit_description(self, node):
        self.body.append( ' ' )
    def depart_description(self, node):
        pass

    def visit_superscript(self, node):
        self.body.append('$^{\\text{')
    def depart_superscript(self, node):
        self.body.append('}}$')

    def visit_subscript(self, node):
        self.body.append('$_{\\text{')
    def depart_subscript(self, node):
        self.body.append('}}$')

    def visit_substitution_definition(self, node):
        raise nodes.SkipNode

    def visit_substitution_reference(self, node):
        raise nodes.SkipNode

    def visit_generated(self, node):
        pass
    def depart_generated(self, node):
        pass

    def visit_compound(self, node):
        pass
    def depart_compound(self, node):
        pass

    def visit_container(self, node):
        pass
    def depart_container(self, node):
        pass

    def visit_decoration(self, node):
        pass
    def depart_decoration(self, node):
        pass

    # text handling

    def encode(self, text):
        text = unicode(text).translate(tex_escape_map)
        if self.literal_whitespace:
            # Insert a blank before the newline, to avoid
            # ! LaTeX Error: There's no line here to end.
            text = text.replace(u'\n', u'~\\\\\n').replace(u' ', u'~')
        return text

    def visit_Text(self, node):
        if self.verbatim is not None:
            self.verbatim += node.astext()
        else:
            text = self.encode(node.astext())
            self.body.append(educateQuotesLatex(text))
    def depart_Text(self, node):
        pass

    def visit_comment(self, node):
        raise nodes.SkipNode

    def visit_system_message(self, node):
        pass
    def depart_system_message(self, node):
        self.body.append('\n')

    def unknown_visit(self, node):
        raise NotImplementedError('Unknown node: ' + node.__class__.__name__)
