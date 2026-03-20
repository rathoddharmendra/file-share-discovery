I want to create a project to assist discover metadata about file shares in a isilon. 
use Isilon APIs-- take step by step. first break down, and ask clarifying questions if in doubt. I want classes and OOPs functions everywhere and clean project. File shares are from 1980's structure and permissions. So, current team is scared about this project permissions..we are collecting data to make data-driven decisions.

Design a good table from migration perspective with normalization and break down if required.. keep it only required fields for simplifications. We are interested in name, server name, pseudioaccess-path name from DFS, type of data(by user), smart quota if any, security groups, 
users in security group, and their
email addresses
, any other meta data pulled (or possible to pull by machines itself about the NAS file share)
python script
>> create a proper property object to store in DB directly from Python to Sqlite.

>> Enricher connnects to Isilon, and enriches the property
>> there is invetory yaml - ip, creds (tell best way to store ir in project or outside project like env variable to define for user in RTE)

>> THERE IS A  main script whih runs enricher for every entry in Isilon..
    >> it also has a logic to check for new shares, and add it or remove not existing ones. It compares agsint local snap file which generates during every run, and helps with above two tasks to speed up.

>> (add logic later) it has web app with RBAC in a traditional company using MSActive directory, to allow users to 
    1. connect only to their shares for write some missing properties in the record. (kept missing from python on purpose for both users and powershell to fill it)
    2. can view all shares data (I can hide it later in feature)

connects to Dell EMC Isilon with YAML, 
creates names of shares, pulls all metadata 
and stores in  sqlite for PS script

let's uses sqlite, and store it in one place

powershell script project (if possible with )
connects to each share from sqlite, 
and finds - security groups, 
users in security group, and their
email addresses


create a good understanding - how to use it, how it woeks, how to contribute to this open source, create open source license etc.  

Write comments that are professional and not obviously auto-generated.

create a makefile to start the project. use docker image to run the project