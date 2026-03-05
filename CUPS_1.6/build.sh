#!/bin/bash

# build.sh
#
# buildscript to build an automake project
#
# Copyright (C) 2012 Intermec Technologies Pte Ltd
#

# Change current directory to where this script resides
SCRIPTPATH=$(cd ${0%/*} && echo $PWD/${0##*/})
SCRIPTDIR=`dirname "$SCRIPTPATH"`
cd $SCRIPTDIR

# Set up temporary variables
AUTORECONFLOG="/tmp/build-autoreconf.log-$$"
CONFIGURELOG="/tmp/build-configure.log-$$"
MAKELOG="/tmp/build-make.log-$$"
MAKEINSTALLLOG="/tmp/build-makeinstall.log-$$"
DEPENDENCYERRLOG="/tmp/build-dependency.log-$$"
DEPENDENCYWARNLOG="/tmp/build-dependencywarn.log-$$"

DEPPROGRAMSERR=(cupsd automake autoconf gcc pnmtoplainpnm pdftoppm pgmtopbm)
DEPPROGRAMSWARN=(ps2pdf)

# Clean up temporary log files
cleanup_tmp_files()
{
  rm -rf ${AUTORECONFLOG} &> /dev/null
  rm -rf ${CONFIGURELOG} &> /dev/null
  rm -rf ${MAKELOG} &> /dev/null
  rm -rf ${MAKEINSTALLLOG} &> /dev/null
  rm -rf ${DEPENDENCYERRLOG} &> /dev/null
  rm -rf ${DEPENDENCYWARNLOG} &> /dev/null
}

# Check Dependencies
echo -en "dependencies...  "
status=0
for i in ${DEPPROGRAMSERR[@]}; do
  command -v ${i} &> /dev/null
  if [ "$?" -ne "0" ]; then
    status=1
    echo "  Error:   Missing utility... ${i}" >> ${DEPENDENCYERRLOG}
  fi
done

for i in ${DEPPROGRAMSWARN[@]}; do
  command -v ${i} &> /dev/null
  if [ "$?" -ne "0" ]; then
    echo "  Warning: Missing utility... ${i}" >> ${DEPENDENCYWARNLOG}
  fi
done

if [ "$status" -ne "0" ]; then
  # Failed
  echo -e "\033[31mFAILED"
  tput sgr0
  echo ""
  cat ${DEPENDENCYERRLOG}
  cat ${DEPENDENCYWARNLOG} 2> /dev/null
  echo ""
  cleanup_tmp_files
  exit 1
else
  # Success
  echo -e "\033[80D\033[35C\033[32m OK"
  tput sgr0
  cat ${DEPENDENCYWARNLOG} 2> /dev/null
fi

# Autoreconf package
echo -en "autoreconf...  "
autoreconf --install --force &> ${AUTORECONFLOG}
if [ "$?" -ne "0" ]; then
  # Failed
  echo -e "\033[31mFAILED"
  tput sgr0
  echo ""
  cat ${AUTORECONFLOG}
  echo ""
  cleanup_tmp_files
  exit 1
else
  # Success
  echo -e "\033[80D\033[35C\033[32m OK"
  tput sgr0
fi

# Configure package
echo -en "configure...   "
./configure &> ${CONFIGURELOG}
if [ "$?" -ne "0" ]; then
  # Failed
  echo -e "\033[31mFAILED"
  tput sgr0
  echo ""
  cat ${CONFIGURELOG}
  echo ""
  cleanup_tmp_files
  exit 1
else
  # Success
  echo -e "\033[80D\033[35C\033[32m OK"
  tput sgr0
fi

# Make package
echo -en "make...        "
make &> ${MAKELOG}
if [ "$?" -ne "0" ]; then
  # Failed
  echo -e "\033[31mFAILED"
  tput sgr0
  echo ""
  cat ${MAKELOG}
  echo ""
  cleanup_tmp_files
  exit 1
else
  # Success
  echo -e "\033[80D\033[35C\033[32m OK"
  tput sgr0
fi

# Make package
echo -en "make install..."
bash -c 'sudo make install-strip' &> ${MAKEINSTALLLOG}
if [ "$?" -ne "0" ]; then
  # Failed
  echo -e "\033[31mFAILED"
  tput sgr0
  echo ""
  cat ${MAKEINSTALLLOG}
  echo ""
  cleanup_tmp_files
  exit 1
else
  # Success
  echo -e "\033[80D\033[35C\033[32m OK"
  tput sgr0
fi

# Cleanup
echo -en "cleanup...     "
cleanup_tmp_files
echo -e "\033[80D\033[35C\033[32m OK"
tput sgr0

PRINTER=`lpstat -p | awk '{print $2}' | sed -n '1p'`
lpadmin -p $PRINTER -o usb-no-reattach-default=true
lpadmin -p $PRINTER -o usb-unidir-default=true
echo "lpadmin -p $PRINTER -o usb-no-reattach-default=true"
echo "lpadmin -p $PRINTER -o usb-unidir-default=true"
