# -*- coding: utf-8 -*-
"""
hydrofunctions.py

This module contains the main functions used in an interactive session.
"""
from __future__ import absolute_import, print_function
import requests
import numpy as np
import pandas as pd
# Change to relative import: from . import exceptions
# https://axialcorps.com/2013/08/29/5-simple-rules-for-building-great-python-packages/
from . import exceptions
import warnings
from . import typing


def get_nwis(site, service, start_date=None, end_date=None, stateCd=None, countyCd=None,
             parameterCd='00060', period=None):
    """Request stream gauge data from the USGS NWIS.

    Args:
        site (str or list of strings):
            a valid site is '01585200' or ['01585200', '01646502']. site
            should be None if stateCd or countyCd are not None.

        service (str):
            can either be 'iv' or 'dv' for instantaneous or daily data.
                'dv'(default): daily values. Mean value for an entire day.
                'iv': instantaneous value measured at this time. Also known
                      as 'Real-time data'. Can be measured as often as every
                      five minutes by the USGS. 15 minutes is more typical.

        start_date (str):
           should take on the form yyyy-mm-dd

        end_date (str):
            should take on the form yyyy-mm-dd

        stateCd (str):
            a valid two-letter state postal abbreviation. Default is None.

        countyCd (str or list of strings):
            a valid county abbreviation. Default is None.

        parameterCd (str):
            NWIS parameter code. Default is stream discharge '00060'
                * stage: '00065'
                * discharge: '00060'
                * not all sites collect all parameters!
                * See https://nwis.waterdata.usgs.gov/usa/nwis/pmcodes for
                  full list

        period (str):
            NWIS period code. Default is None.
                * Format is "PxxD", where xx is the number of days before
                today, with a maximum of 999 days accepted.
                * Either use start_date or period, but not both.

    Returns:
        a response object. This function will always return the response,
            even if the NWIS returns a status_code that indicates a problem.

            * response.url: the url we used to request data
            * response.status_code: '200' when okay; see
            <https://www.w3.org/Protocols/rfc2616/rfc2616-sec10.html>
            * response.json: the content translated as json
            * response.status_code: the internet status code
                - '200': is a good request
                - non-200 codes will be reported as a warning.
                - '400': is a 'Bad Request'-- the parameters did not make sense
            * response.ok: "True" when we get a '200' status_code

    Raises:
        ConnectionError: due to connection problems like refused connection
            or DNS Error.

        SyntaxWarning: when NWIS returns a response code that is not 200.

    Example::

        >>> import hydrofunctions as hf
        >>> response = hf.get_nwis('01585200', 'dv', '2012-06-01', '2012-07-01')

        >>> response
        <response [200]>

        >>> response.json()
        *JSON ensues*

        >>> hf.extract_nwis_df(response)
        *a Pandas dataframe appears*

    Other Valid Ways to Make a Request::

        >>> sites = ['07180500', '03380475', '06926000'] # Request a list of sites.
        >>> service = 'iv'  # Request real-time data
        >>> days = 'P10D'  # Request the last 10 days.
        >>> stage = '00065' # Sites that collect discharge usually collect water depth too.
        >>> response2 = hf.get_nwis(sites, service, period=days, parameterCd=stage)

    Request Data By Location::

        >>> # Request the most recent daily data for every site in Maine
        >>> response3 = hf.get_nwis(None, 'dv', stateCd='ME')
        >>> response3
        <Response [200]>

    The specification for the USGS NWIS IV service is located here:
    http://waterservices.usgs.gov/rest/IV-Service.html
    """

    header = {
        'Accept-encoding': 'gzip',
        'max-age': '120'
        }

    values = {
        # specify version of nwis json. Based on WaterML1.1
        # json,1.1 works; json%2C works; json1.1 DOES NOT WORK
        'format': 'json,1.1',
        # 'sites': sites,
        # default parameterCd represents stream discharge.
        'parameterCd': parameterCd,
        # This is the format for requesting 10 days of data before today.
        'period': period,
        'startDT': start_date,
        'endDT': end_date
        }

    # process sites, stateCd, or countyCd options
    if stateCd is None and countyCd is None:
        sites = typing.check_NWIS_site(site)
        values['sites'] = sites
    elif stateCd is not None:
        values['stateCd'] = stateCd
    elif countyCd is not None:
        countyCd = typing.check_NWIS_site(countyCd)
        values['countyCd'] = countyCd

    url = 'http://waterservices.usgs.gov/nwis/'
    url = url + service + '/?'
    response = requests.get(url, params=values, headers=header)
    # requests will raise a 'ConnectionError' if the connection is refused
    # or if we are disconnected from the internet.

    # .get_nwis() will always return the response.

    # Higher-level code that calls get_nwis() may decide to handle or
    # report status codes that indicate something went wrong.

    # Issue warnings for bad status codes
    nwis_custom_status_codes(response)

    return response


def extract_nwis_df(response_obj):
    """Returns a Pandas dataframe from an NWIS response object.

    Args:
        response_obj (obj):
            a response object as returned by get_nwis().

    Returns:
        a pandas dataframe.

    Raises:
        HydroNoDataError  when the request is valid, but NWIS has no data for
            the parameters provided in the request.
    """
    nwis_dict = response_obj.json()

    # strip header and all metadata.
    ts = nwis_dict['value']['timeSeries']
    if ts == []:
        # raise a HydroNoDataError if NWIS returns an empty set.
        #
        # Ideally, an empty set exception would be raised when the request
        # is first returned, but I do it here so that the data doesn't get
        # extracted twice.
        # TODO: raise this exception earlier??
        # TODO: find a URL will result an empty set like this.
        #
        # ** Interactive sessions should have an error raised.
        #
        # **Automated systems should catch these errors and deal with them.
        # In this case, if NWIS returns an empty set, then the request
        # needs to be reconsidered. The request was valid somehow, but
        # there is no data being collected.

        # TODO: this if clause needs to be tested.
        raise exceptions.HydroNoDataError("The NWIS reports that it does not"
                                          " have any data for this request.")

    # create lists of timeseries keys, names, and noDataValues
    keys = []
    names = []
    noDataValues = []
    for idx, tts in enumerate(ts):
        keys.append(idx)
        tag = tts['name'].split(':')[1]
        tag += ' - '
        try:
            tag += tts['variable']['options']['option'][0]['value']
        # TODO: either list specific exceptions that we can fix, or remove this
        # except clause.
        except:
            pass
        tag += ' ' + tts['variable']['variableDescription']
        names.append(tag)
        ndv = tts['variable']['noDataValue']
        if ndv not in noDataValues:
            noDataValues.append(ndv)

    # determine the NWIS data item with the maximum amount of data so that
    # it can be processed first
    idxmx = 0
    emax = 0
    for idx, key in enumerate(keys):
        data = nwis_dict['value']['timeSeries'][key]['values'][0]['value']
        if len(data) > emax:
            emax = len(data)
            idxmx = idx

    # process data for the first NWIS site
    data = nwis_dict['value']['timeSeries'][idxmx]['values'][0]['value']
    DF = pd.DataFrame(data, columns=['dateTime', 'value'])
    DF.index = pd.to_datetime(DF.pop('dateTime'))
    DF = DF.rename(columns={'value': names[idxmx]})
    DF[names[idxmx]] = DF[names[idxmx]].astype(float)

    # set index name for dataframe
    DF.index.name = 'datetime'

    # process data for the remaining NWIS sites
    for key in keys:
        # skip data processing if key has already been processed
        if key == idxmx:
            continue
        da = nwis_dict['value']['timeSeries'][key]['values'][0]['value']
        dfa = pd.DataFrame(da, columns=['dateTime', 'value'])
        dfa.index = pd.to_datetime(dfa.pop('dateTime'))
        dfa = dfa.rename(columns={'value': names[key]})
        DF = pd.concat([DF, dfa], axis=1)
        DF[names[key]] = DF[names[key]].astype(float)

    # replace missing values in the dataframe
    DF = DF.replace(to_replace=noDataValues, value=np.nan)

    return DF


def nwis_custom_status_codes(response):
    """
    Raise custom warning messages from the NWIS when it returns a
    status_code that is not 200.

    Args:
        response: a response object as returned by get_nwis().

    Returns:
        None: if response.status_code == 200
        response.status_code: for all other status codes.

    Raises:
        SyntaxWarning: when a non-200 status code is returned.
            https://en.wikipedia.org/wiki/List_of_HTTP_status_codes

    Note:
        To raise an exception, call `response.raise_for_status()`
        This will raise requests.exceptions.HTTPError with a helpful message
        or it will return None for status code 200.
        From: http://docs.python-requests.org/en/master/user/quickstart/#response-status-codes

        NWIS status_code messages come from:
            https://waterservices.usgs.gov/docs/portable_code.html
        Additional status code documentation:
            https://waterservices.usgs.gov/rest/IV-Service.html#Error
    """
    nwis_msg = {
            '200': 'OK',
            '400': "400 Bad Request - "
                   "This often occurs if the URL arguments "
                   "are inconsistent, for example in the instantaneous values "
                   "service using startDT and endDT with the period argument. "
                   "An accompanying error should describe why the request was "
                   "bad."
                   + "\nError message from NWIS: {}".format(response.reason),
            '403': "403 Access Forbidden - "
                   "This should only occur if for some reason the USGS has "
                   "blocked your Internet Protocol (IP) address from using "
                   "the service. This can happen if we believe that your use "
                   "of the service is so excessive that it is seriously "
                   "impacting others using the service. To get unblocked, "
                   "send us the URL you are using along with the IP using "
                   "this form. We may require changes to your query and "
                   "frequency of use in order to give you access to the "
                   "service again.",
            '404': "404 Not Found - "
                   "Returned if and only if the query expresses a combination "
                   "of elements where data do not exist. For multi-site "
                   "queries, if any data are found, it is returned for those "
                   "site/parameters/date ranges where there are data.",
            '503': "500 Internal Server Error - "
                   "If you see this, it means there is a problem with the web "
                   "service itself. It usually means the application server "
                   "is down unexpectedly. This could be caused by a host of "
                   "conditions but changing your query will not solve this "
                   "problem. The application support team has to fix it. Most "
                   "of these errors are quickly detected and the support team "
                   "is notified if they occur."
            }
    if response.status_code == 200:
        return None
    # All other status codes will raise a warning.
    else:
        # Use the status_code as a key, return None if key not in dict
        msg = "The NWIS returned a code of {}.\n".format(response.status_code)\
              + nwis_msg.get(str(response.status_code))\
              + "\n\nURL used in this request: {}".format(response.url)

        # Warnings will not beak the flow. They just print a message.
        # However, they are often supressed in some applications.
        warnings.warn(msg, SyntaxWarning)
        return response.status_code
