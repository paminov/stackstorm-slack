#!/usr/bin/env python
# -*- coding: utf-8 -*-

# StdLib
import os
import re
import json

# External
from bs4 import BeautifulSoup
from jinja2 import Environment, FileSystemLoader
import requests
import six
from prance import ResolvingParser

OPENAPI_JSON_URL = 'https://raw.githubusercontent.com/slackapi/slack-api-specs/master/web-api/slack_web_openapi_v2.json'

METHOD_OVERRIDES = {
}

SLACK_SESSION = requests.Session()


def get_openapi_spec():
    parser = ResolvingParser(OPENAPI_JSON_URL)
    return parser.specification  # contains fully resolved specs as a dict


def get_spec_from_http_reference(method):
    page = SLACK_SESSION.get("https://api.slack.com/methods/" + method)
    soup = BeautifulSoup(page.text, "lxml")

    # find the HTTP method
    method_facts_table = soup.find('h2', attrs={"id": "facts"}).findNext('table')
    method_header = method_facts_table.find('th', text='Preferred HTTP method:')
    http_method = method_header.findNext('td').text.strip()

    # find  <div class="method_arguments">
    # this is the table with all of the API parameters it in
    arguments_table = soup.find('div', class_='method_arguments full_width')
    # within this table, each argument has its own <div class="method_argument>
    arguments = arguments_table.find_all('div', class_='method_argument')
    params = {}
    for arg in arguments:
        # the name of this argument lives in a <span class="arg_name">
        arg_name = arg.find('span', class_='arg_name')
        # the actual name is a <a href=""> link and the argument is the text
        # within the link
        arg_name_link = arg_name.find('a')
        name = arg_name_link.text

        # the next thing we want to grab is the default value
        # this lives in its own <span class="arg_cell arg_desc">
        arg_desc = arg.find('span', class_="arg_cell arg_desc")
        # the default value lives in one of the paragraph <p> tags
        # so we find all of the <p> tags and try to search for the text "Default:"
        paragraphs = arg_desc.find_all('p')
        default = None
        for p in paragraphs:
            # we found a paragraph tag with our default value
            if 'Default:' in p.text:
                default = p.text.split('Default:')[1].strip()
                try:
                    # try to parse the default as JSON, this allows us to treat
                    # integers and booleans as their native type rather than as strings
                    # for everything
                    default = json.loads(default)
                except json.decoder.JSONDecodeError:
                    pass
            # save the default, we want to save this even if it's None so
            # that the template can skip defaults that are set to None
            params[name] = {'default': default}

    http_ref_spec = {
        'params': params,
        'http_method': http_method,
    }
    return http_ref_spec


def get_params_from_openapi_operation(openapi_operation, params_http_ref):
    parameters = []
    for p in sorted(openapi_operation['parameters'], key=lambda i: i['name']):
        name = p['name']
        default = p.get('default')
        # if the OpenAPI spec doesn't have a default set (currently it does not)
        # try to grab the default from the HTTP reference documentation online
        if not default and name in params_http_ref:
            default = params_http_ref[name]['default']
        parameters.append({
            'name': name,
            'type': p['type'],
            'description': p.get('description'),
            'default': default,
            'required': p.get('required', False)
        })
    return parameters


def main():
    api_spec = get_openapi_spec()

    pack_bin_path = os.path.dirname(os.path.abspath(__file__))
    pack_root_path = os.path.dirname(pack_bin_path)
    pack_actions_path = os.path.join(pack_root_path, 'actions')
    env = Environment(loader=FileSystemLoader(pack_bin_path))
    template = env.get_template('template.jinja')

    # get all of the methods and parmaters from OpenAPI
    # will need to get the Default values from the Web API spec because
    # OpenAPI doesn't have them defined (yet)
    # https://github.com/slackapi/slack-api-specs/issues/40
    for path, http_methods in six.iteritems(api_spec['paths']):
        for http_method, op in six.iteritems(http_methods):
            method = path.replace('/', '')
            http_method = http_method.upper()
            http_ref_spec = get_spec_from_http_reference(method)
            params = get_params_from_openapi_operation(op, http_ref_spec['params'])
            if http_method != http_ref_spec['http_method']:
                print(("WARNING - http method is not the same for [{}] openapi={} http_ref={}"
                       " - defaulting to the preferred method from the HTTP reference.")
                      .format(method, http_method, http_ref_spec['http_method']))
                http_method = http_ref_spec['http_method']

            rendered = template.render(description=op['description'],
                                       http_method=http_method,
                                       method=method,
                                       parameters=params)

            with open('{}.yaml'.format(os.path.join(pack_actions_path, method)), "w") as _f:
                _f.write(rendered + "\n")


if __name__ == "__main__":
    main()
